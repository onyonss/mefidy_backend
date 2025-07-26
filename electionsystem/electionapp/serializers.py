from rest_framework import serializers
from .models import User, Election, Utilisateur, Vote, ListeCandidats, Activite
import logging
logger = logging.getLogger(__name__)

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)

class FirstLoginSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, required=True)

class ActiviteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Activite
        fields = ['id', 'nom']

class UtilisateurSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    nom = serializers.CharField()
    username = serializers.CharField(source='user.username')
    matricule = serializers.CharField()
    annee_universitaire = serializers.CharField()
    fingerprint_id = serializers.CharField(allow_blank=True, required=False)
    classe = serializers.ChoiceField(choices=Utilisateur.CLASSE_CHOICES)
    mention = serializers.ChoiceField(choices=Utilisateur.MENTION_CHOICES)
    activites = ActiviteSerializer(many=True, read_only=True)
    activite_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    sport_type = serializers.ChoiceField(choices=Utilisateur.SPORT_SUBCHOICES, allow_null=True)
    vote_count = serializers.SerializerMethodField()
    has_voted = serializers.SerializerMethodField()

    class Meta:
        model = Utilisateur
        fields = [
            'id', 'nom', 'username', 'matricule', 'annee_universitaire',
            'fingerprint_id', 'classe', 'mention', 'activites', 'activite_ids', 'sport_type',
            'vote_count', 'has_voted'
        ]

    def get_vote_count(self, obj):
        election = self.context.get('election')
        return obj.get_vote_count(election) if election else 0

    def get_has_voted(self, obj):
        election = self.context.get('election')
        if election:
            return obj.has_voted(election)
        return False

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        activite_ids = validated_data.pop('activite_ids', None)
        instance.nom = validated_data.get('nom', instance.nom)
        instance.matricule = validated_data.get('matricule', instance.matricule)
        instance.annee_universitaire = validated_data.get('annee_universitaire', instance.annee_universitaire)
        instance.classe = validated_data.get('classe', instance.classe)
        instance.mention = validated_data.get('mention', instance.mention)
        instance.sport_type = validated_data.get('sport_type', instance.sport_type)
        if activite_ids is not None:
            instance.activites.set(Activite.objects.filter(id__in=activite_ids))
        instance.user.username = user_data.get('username', instance.user.username)
        if validated_data.get('password'):
            instance.user.set_password(validated_data['password'])
        instance.user.save()
        instance.save()
        return instance

class UtilisateurCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=True)
    matricule = serializers.CharField(max_length=4, required=True)
    annee_universitaire = serializers.CharField(max_length=9, required=True)
    nom = serializers.CharField(max_length=250, required=True)
    classe = serializers.ChoiceField(choices=Utilisateur.CLASSE_CHOICES, default=1)
    mention = serializers.ChoiceField(choices=Utilisateur.MENTION_CHOICES, default='INFO')
    activite_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=[])
    sport_type = serializers.ChoiceField(choices=Utilisateur.SPORT_SUBCHOICES, required=False, allow_null=True)

    def validate_matricule(self, value):
        if not value.isdigit() or len(value) != 4:
            raise serializers.ValidationError("Matricule must be a 4-digit number")
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['matricule']
        )
        utilisateur = Utilisateur.objects.create(
            nom=validated_data['nom'],
            matricule=validated_data['matricule'],
            annee_universitaire=validated_data['annee_universitaire'],
            is_first_login=True,
            user=user,
            classe=validated_data['classe'],
            mention=validated_data['mention'],
            sport_type=validated_data['sport_type']
        )
        activite_ids = validated_data.get('activite_ids', [])
        if activite_ids:
            utilisateur.activites.set(Activite.objects.filter(id__in=activite_ids))
        return utilisateur

class ListeCandidatsSerializer(serializers.ModelSerializer):
    candidats = UtilisateurSerializer(many=True, read_only=True)
    candidate_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = ListeCandidats
        fields = ['id', 'nom', 'candidats', 'candidate_ids']

    def create(self, validated_data):
        candidate_ids = validated_data.pop('candidate_ids', None)
        instance = ListeCandidats.objects.create(**validated_data)
        if candidate_ids:
            candidates = Utilisateur.objects.filter(id__in=candidate_ids)
            instance.candidats.set(candidates)
        return instance

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        logger.info(f"Serializing ListeCandidats id={instance.id}, nom={instance.nom}, candidats_count={instance.candidats.count()}, candidats={[c['nom'] for c in representation['candidats']]}")
        return representation

class ElectionSerializer(serializers.ModelSerializer):
    listeCandidats_id = serializers.PrimaryKeyRelatedField(
        queryset=ListeCandidats.objects.all(), source='listeCandidats', write_only=True, allow_null=True
    )
    allowed_voter_criteria = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField(), allow_empty=True),
        required=False
    )
    listeCandidats = ListeCandidatsSerializer(read_only=True)
    candidate_votes = serializers.SerializerMethodField()
    total_voters = serializers.SerializerMethodField()
    voters_who_voted = serializers.SerializerMethodField()
    can_vote = serializers.SerializerMethodField()

    class Meta:
        model = Election
        fields = [
            'id', 'nom', 'startdate', 'enddate', 'statut',
            'listeCandidats', 'listeCandidats_id', 'allowed_voter_criteria',
            'candidate_votes', 'total_voters', 'voters_who_voted', 'can_vote'
        ]

    def get_candidate_votes(self, obj):
        return {candidate.nom: candidate.get_vote_count(obj) for candidate in obj.listeCandidats.candidats.all()}

    def get_total_voters(self, obj):
        return len([u for u in Utilisateur.objects.all() if obj.is_voter_allowed(u)])

    def get_voters_who_voted(self, obj):
        return obj.votes.filter(electeur__in=[
            u for u in Utilisateur.objects.all() if obj.is_voter_allowed(u)
        ], estNul=False).count()

    def get_can_vote(self, obj):
        user = self.context['request'].user
        if user.is_staff:
            return False
        try:
            utilisateur = Utilisateur.objects.get(user=user)
            return (
                obj.is_voter_allowed(utilisateur) and
                not utilisateur.has_voted(obj) and
                obj.is_open()
            )
        except Utilisateur.DoesNotExist:
            return False

    def validate(self, data):
        startdate = data.get('startdate')
        enddate = data.get('enddate')
        liste_candidats = data.get('listeCandidats')
        allowed_voter_criteria = data.get('allowed_voter_criteria', {})
        if startdate and enddate and startdate >= enddate:
            raise serializers.ValidationError("Start date must be before end date")
        if liste_candidats and liste_candidats.candidats.count() == 0:
            raise serializers.ValidationError("La liste de candidats doit contenir au moins un candidat")
        if allowed_voter_criteria.get('classe'):
            allowed_voter_criteria['classe'] = [str(c) for c in allowed_voter_criteria['classe']]
        if allowed_voter_criteria.get('activite') and 'SPORT' in allowed_voter_criteria.get('activite', []):
            if not allowed_voter_criteria.get('sport_type'):
                allowed_voter_criteria['sport_type'] = []
        else:
            allowed_voter_criteria['sport_type'] = []
        data['allowed_voter_criteria'] = allowed_voter_criteria
        return data