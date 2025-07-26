from django.db import models
from django.contrib.auth.models import User
import logging

ELECTION_STATUS_CHOICES = (("ouvert", "ouvert"), ("ferme", "ferme"))
logger = logging.getLogger(__name__)

class Activite(models.Model):
    ACTIVITE_CHOICES = (
        ('DANSE', 'Danse'), ('SPORT', 'Sport'), ('CHANT', 'Chant'), ('DESSIN', 'Dessin'), ('SLAM', 'Slam'),
    )
    nom = models.CharField(max_length=10, choices=ACTIVITE_CHOICES, unique=True)

    def __str__(self):
        return self.nom

class Utilisateur(models.Model):
    CLASSE_CHOICES = (
        (1, 'L1'), (2, 'L2'), (3, 'L3'), (4, 'M1'), (5, 'M2'),
    )
    MENTION_CHOICES = (
        ('INFO', 'Informatique'), ('SA', 'Sciences Agronomiques'), ('ECO', 'Économie et Commerce'),
        ('LEA', 'Langues Étrangères Appliquées'), ('ST', 'Sciences de la Terre'), ('DROIT', 'Droit'),
    )
    SPORT_SUBCHOICES = (
        ('FOOT', 'Football'), ('BASKET', 'Basketball'), ('VOLLEY', 'Volleyball'), ('PET', 'Pétanque'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_index=True)
    matricule = models.CharField(max_length=4, unique=True)
    nom = models.CharField(max_length=250)
    annee_universitaire = models.CharField(max_length=9, default="2024-2025")
    classe = models.IntegerField(choices=CLASSE_CHOICES, default=1)
    mention = models.CharField(max_length=10, choices=MENTION_CHOICES, default='INFO')
    fingerprint_id = models.CharField(max_length=10, null=True, blank=True)
    activites = models.ManyToManyField(Activite, blank=True)
    sport_type = models.CharField(max_length=10, choices=SPORT_SUBCHOICES, null=True, blank=True)
    is_first_login = models.BooleanField(default=True)

    def voter(self, candidat, election):
        if not self.has_voted(election):
            vote = Vote.objects.create(electeur=self, choix=candidat, estNul=False, election=election)
            return vote
        raise ValueError("La personne a déjà voté dans cette élection")

    def has_voted(self, election):
        return Vote.objects.filter(electeur=self, election=election).exists()

    def get_vote_count(self, election):
        return Vote.objects.filter(choix=self, election=election, estNul=False).count()

    def __str__(self):
        return self.nom

class Vote(models.Model):
    electeur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, db_index=True, related_name='votes_cast')
    choix = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, db_index=True, related_name='votes_received')
    election = models.ForeignKey('Election', on_delete=models.CASCADE, db_index=True, related_name='votes')
    estNul = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def enregistrerVote(self):
        if self.choix in self.election.listeCandidats.candidats.all():
            self.estNul = False
        self.save()

class ListeCandidats(models.Model):
    nom = models.CharField(max_length=100)
    candidats = models.ManyToManyField(Utilisateur)

    def __str__(self):
        return self.nom

class Election(models.Model):
    nom = models.CharField(max_length=250)
    startdate = models.DateTimeField()
    enddate = models.DateTimeField()
    statut = models.CharField(max_length=50, choices=ELECTION_STATUS_CHOICES, default="ouvert")
    listeCandidats = models.ForeignKey(ListeCandidats, on_delete=models.CASCADE, null=True, blank=True)
    allowed_voter_criteria = models.JSONField(default=dict)
    resultat = models.OneToOneField('Resultat', on_delete=models.CASCADE, null=True, blank=True, related_name='related_election')

    def is_open(self):
        from django.utils import timezone
        return self.statut == "ouvert" and timezone.now() <= self.enddate

    def is_voter_allowed(self, utilisateur):
        criteria = self.allowed_voter_criteria or {}
        user_classe = str(utilisateur.classe)
        logger.info(f"Checking is_voter_allowed for user classe={user_classe}, criteria={criteria}")
        classe_allowed = not criteria.get('classe') or len(criteria.get('classe', [])) == 0 or user_classe in criteria.get('classe', [])
        mention_allowed = not criteria.get('mention') or len(criteria.get('mention', [])) == 0 or utilisateur.mention in criteria.get('mention', [])
        activite_allowed = not criteria.get('activite') or len(criteria.get('activite', [])) == 0 or any(activite.nom in criteria.get('activite', []) for activite in utilisateur.activites.all())
        sport_type_allowed = True
        if criteria.get('activite') and 'SPORT' in criteria.get('activite', []) and criteria.get('sport_type'):
            if any(activite.nom == 'SPORT' for activite in utilisateur.activites.all()):
                sport_type_allowed = len(criteria.get('sport_type', [])) == 0 or utilisateur.sport_type in criteria.get('sport_type', [])
        allowed = classe_allowed and mention_allowed and activite_allowed and sport_type_allowed
        logger.info(f"Result: classe_allowed={classe_allowed}, mention_allowed={mention_allowed}, activite_allowed={activite_allowed}, sport_type_allowed={sport_type_allowed}, allowed={allowed}")
        return allowed

    def clean(self):
        if self.startdate > self.enddate:
            raise ValueError("Start date must be before end date")

    class Meta:
        indexes = [models.Index(fields=['startdate', 'enddate']), models.Index(fields=['statut'])]

class Resultat(models.Model):
    election = models.ForeignKey('Election', on_delete=models.CASCADE, db_index=True, related_name='resultat_set')
    listeVote = models.ManyToManyField('Vote')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calculerResultats(self):
        votes = self.listeVote.all()
        result = {}
        for vote in votes:
            if not vote.estNul:
                candidate = vote.choix.nom
                result[candidate] = result.get(candidate, 0) + 1
        return result