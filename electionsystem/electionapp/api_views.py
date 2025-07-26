import pandas as pd
from io import BytesIO
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.conf import settings
from .models import Election, Utilisateur, Vote, Resultat, ListeCandidats, Activite
from .serializers import ElectionSerializer, UtilisateurSerializer, UtilisateurCreateSerializer, LoginSerializer, ListeCandidatsSerializer, FirstLoginSerializer
from rest_framework_simplejwt.tokens import RefreshToken
import logging
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from openpyxl import Workbook
from django.http import HttpResponse
from .serial_reader import get_fingerprint_from_sensor
import serial

logger = logging.getLogger(__name__)

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def get_token(self, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['is_staff'] = user.is_staff
        token['is_superuser'] = user.is_superuser
        logger.info(f"Custom token payload for {user.username}: {token.payload}")
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        try:
            utilisateur = Utilisateur.objects.get(user=user)
            data['is_first_login'] = utilisateur.is_first_login
        except Utilisateur.DoesNotExist:
            data['is_first_login'] = False
        return data

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

class LoginAPIView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            user = authenticate(username=username, password=password)
            if user:
                try:
                    utilisateur = Utilisateur.objects.get(user=user)
                    refresh = RefreshToken.for_user(user)
                    logger.info(f"User {username} logged in")
                    return Response({
                        'refresh': str(refresh),
                        'access': str(refresh.access_token),
                        'user_id': user.id,
                        'is_first_login': utilisateur.is_first_login
                    }, status=status.HTTP_200_OK)
                except Utilisateur.DoesNotExist:
                    return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class FirstLoginAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FirstLoginSerializer(data=request.data)
        if serializer.is_valid():
            try:
                utilisateur = Utilisateur.objects.get(user=request.user)
                if not utilisateur.is_first_login:
                    return Response({"error": "Not first login"}, status=status.HTTP_400_BAD_REQUEST)
                new_password = serializer.validated_data['new_password']
                try:
                    fingerprint_id = get_fingerprint_from_sensor(mode='enroll', user_id=utilisateur.id)
                    if not fingerprint_id:
                        logger.error("Failed to enroll fingerprint")
                        return Response({"error": "Failed to enroll fingerprint"}, status=status.HTTP_400_BAD_REQUEST)
                    utilisateur.fingerprint_id = fingerprint_id
                    utilisateur.user.set_password(new_password)
                    utilisateur.is_first_login = False
                    utilisateur.user.save()
                    utilisateur.save()
                    logger.info(f"First login completed for {request.user.username}, fingerprint_id={fingerprint_id}")
                    return Response({"message": "Password and fingerprint updated"}, status=status.HTTP_200_OK)
                except serial.serialutil.SerialException as e:
                    logger.error(f"Serial error: {str(e)}")
                    return Response({"error": "Failed to communicate with fingerprint sensor"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Utilisateur.DoesNotExist:
                return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"Fingerprint error: {str(e)}")
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        logger.error(f"Serializer errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class FingerprintVerifyAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            utilisateur = Utilisateur.objects.get(user=request.user)
            fingerprint_id = get_fingerprint_from_sensor(mode='verify')
            if fingerprint_id and fingerprint_id == utilisateur.fingerprint_id:
                logger.info(f"Fingerprint verified for user {request.user.username}, fingerprint_id={fingerprint_id}")
                return Response({"message": "Fingerprint verified"}, status=status.HTTP_200_OK)
            logger.error(f"Fingerprint verification failed for {request.user.username}, received_id={fingerprint_id}, expected_id={utilisateur.fingerprint_id}")
            return Response({"error": "Fingerprint verification failed"}, status=status.HTTP_400_BAD_REQUEST)
        except Utilisateur.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except serial.serialutil.SerialException as e:
            logger.error(f"Serial error: {str(e)}")
            return Response({"error": "Failed to communicate with fingerprint sensor"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Verification error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class UserImportAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            logger.error("No file uploaded")
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        if not file.name.endswith(('.xlsx', '.xls')):
            logger.error(f"Invalid file format: {file.name}")
            return Response({"error": "Invalid file format"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            df = pd.read_excel(file)
            logger.info(f"Excel columns: {list(df.columns)}")
            required_columns = ['matricule', 'nom', 'username', 'annee_universitaire', 'classe', 'mention', 'activites']
            if not all(col in df.columns for col in required_columns):
                missing = [col for col in required_columns if col not in df.columns]
                logger.error(f"Missing required columns: {missing}")
                return Response({"error": f"Missing required columns: {missing}"}, status=status.HTTP_400_BAD_REQUEST)
            created_count = 0
            updated_count = 0
            for index, row in df.iterrows():
                matricule = str(row['matricule']).strip()
                if not matricule.isdigit() or len(matricule) != 4:
                    logger.warning(f"Invalid matricule at row {index + 2}: {matricule}")
                    continue
                activites = str(row['activites']).strip().split(',') if pd.notna(row['activites']) else []
                activite_ids = []
                for activite in activites:
                    activite = activite.strip().upper()
                    if activite in [choice[0] for choice in Activite.ACTIVITE_CHOICES]:
                        activite_obj, _ = Activite.objects.get_or_create(nom=activite)
                        activite_ids.append(activite_obj.id)
                data = {
                    'matricule': matricule,
                    'nom': str(row['nom']).strip(),
                    'username': str(row['username']).strip(),
                    'annee_universitaire': str(row['annee_universitaire']).strip(),
                    'classe': int(row['classe']),
                    'mention': str(row['mention']).strip(),
                    'activite_ids': activite_ids,
                    'sport_type': str(row['sport_type']).strip() if 'sport_type' in df.columns and pd.notna(row['sport_type']) else None,
                }
                logger.info(f"Processing row {index + 2}: {data}")
                try:
                    utilisateur = Utilisateur.objects.get(matricule=matricule)
                    user = utilisateur.user
                    user.username = data['username']
                    user.save()
                    utilisateur.nom = data['nom']
                    utilisateur.annee_universitaire = data['annee_universitaire']
                    utilisateur.classe = data['classe']
                    utilisateur.mention = data['mention']
                    utilisateur.sport_type = data['sport_type']
                    utilisateur.is_first_login = True
                    utilisateur.save()
                    utilisateur.activites.set(Activite.objects.filter(id__in=data['activite_ids']))
                    updated_count += 1
                except Utilisateur.DoesNotExist:
                    if User.objects.filter(username=data['username']).exists():
                        logger.warning(f"Username {data['username']} already exists at row {index + 2}")
                        continue
                    user = User.objects.create_user(
                        username=data['username'],
                        password=data['matricule']
                    )
                    utilisateur = Utilisateur.objects.create(
                        nom=data['nom'],
                        matricule=data['matricule'],
                        annee_universitaire=data['annee_universitaire'],
                        is_first_login=True,
                        user=user,
                        classe=data['classe'],
                        mention=data['mention'],
                        sport_type=data['sport_type']
                    )
                    utilisateur.activites.set(Activite.objects.filter(id__in=data['activite_ids']))
                    created_count += 1
            logger.info(f"Imported {created_count} new users, updated {updated_count} users")
            return Response({"message": f"Imported {created_count} new users, updated {updated_count} users"}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Import error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ListeCandidatsCreateAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = ListeCandidatsSerializer(data=request.data)
        if serializer.is_valid():
            candidate_ids = request.data.get('candidate_ids', [])
            if not candidate_ids:
                return Response({"error": "At least one candidate is required"}, status=status.HTTP_400_BAD_REQUEST)
            liste_candidats = serializer.save()
            candidates = Utilisateur.objects.filter(id__in=candidate_ids)
            liste_candidats.candidats.set(candidates)
            logger.info(f"ListeCandidats {liste_candidats.nom} created by {request.user.username}, candidates={[c.nom for c in liste_candidats.candidats.all()]}")
            return Response(ListeCandidatsSerializer(liste_candidats).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ListeCandidatsListAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        listes = ListeCandidats.objects.prefetch_related('candidats').all()
        serializer = ListeCandidatsSerializer(listes, many=True)
        logger.info(f"Returning {len(listes)} candidate lists")
        return Response(serializer.data)

class ElectionListCreateAPIView(generics.ListCreateAPIView):
    queryset = Election.objects.all()
    serializer_class = ElectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        logger.info(f"Filtering elections for user {user.username} (id={user.id})")
        if user.is_staff or user.is_superuser:
            logger.info("User is admin, returning all elections")
            return Election.objects.all()
        try:
            utilisateur = Utilisateur.objects.get(user=user)
            logger.info(f"Utilisateur found: {utilisateur}, classe: {utilisateur.classe}")
            allowed_elections = []
            for election in Election.objects.all():
                logger.info(f"Checking election {election.nom} (id={election.id}), allowed_voter_criteria={election.allowed_voter_criteria}")
                if election.is_voter_allowed(utilisateur):
                    logger.info(f"Election {election.nom} is allowed for user")
                    allowed_elections.append(election.id)
            queryset = Election.objects.filter(id__in=allowed_elections)
            logger.info(f"Returning {queryset.count()} elections: {[e.id for e in queryset]}")
            return queryset
        except Utilisateur.DoesNotExist:
            logger.warning(f"No Utilisateur found for user {user.username}")
            return Election.objects.none()

    def post(self, request):
        if not request.user.is_staff:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        serializer = ElectionSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            election = serializer.save()
            logger.info(f"Election {election.nom} created by {request.user.username}, listeCandidats={election.listeCandidats.nom if election.listeCandidats else None}, candidates={[c.nom for c in election.listeCandidats.candidats.all()] if election.listeCandidats else []}")
            return Response(ElectionSerializer(election, context={'request': request}).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ElectionDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, idElection):
        logger.info(f"Fetching election with id={idElection} for user={request.user.username}")
        election = get_object_or_404(Election, id=idElection)
        if request.user.is_staff:
            serializer = ElectionSerializer(election, context={'request': request})
            return Response(serializer.data)
        try:
            utilisateur = Utilisateur.objects.get(user=request.user)
            if not election.is_voter_allowed(utilisateur):
                return Response({"error": "Accès non autorisé"}, status=status.HTTP_403_FORBIDDEN)
        except Utilisateur.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)
        serializer = ElectionSerializer(election, context={'request': request})
        return Response(serializer.data)

    def put(self, request, idElection):
        if not request.user.is_staff:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        election = get_object_or_404(Election, id=idElection)
        serializer = ElectionSerializer(election, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Election {election.nom} updated by {request.user.username}")
            return Response(ElectionSerializer(election, context={'request': request}).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, idElection):
        if not request.user.is_staff:
            return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
        election = get_object_or_404(Election, id=idElection)
        election.delete()
        logger.info(f"Election {idElection} deleted by {request.user.username}")
        return Response(status=status.HTTP_204_NO_CONTENT)

class VoterAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, idElection):
        logger.info(f"Vote attempt by user {request.user.id} for election {idElection}")
        election = get_object_or_404(Election, id=idElection)
        if not election.is_open():
            return Response({"error": "Cette élection est fermée"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            utilisateur = Utilisateur.objects.get(user=request.user)
        except Utilisateur.DoesNotExist:
            return Response({"error": "Utilisateur non autorisé à voter"}, status=status.HTTP_403_FORBIDDEN)
        if not election.is_voter_allowed(utilisateur):
            return Response({"error": "Type d'utilisateur non autorisé à voter"}, status=status.HTTP_403_FORBIDDEN)
        if utilisateur.has_voted(election):
            return Response({"error": "Vous avez déjà voté"}, status=status.HTTP_400_BAD_REQUEST)
        candidate_id = request.data.get('candidate')
        try:
            candidat = get_object_or_404(Utilisateur, id=candidate_id)
            if candidat not in election.listeCandidats.candidats.all():
                return Response({"error": "Candidat non valide pour cette élection"}, status=status.HTTP_400_BAD_REQUEST)
            vote = utilisateur.voter(candidat, election)
            vote.enregistrerVote()
            logger.info(f"Vote recorded for {candidat.nom} by {request.user.username}")
            return Response({"message": "Vote enregistré avec succès"}, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Vote error: {str(e)}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class PublierResultatsAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, idElection):
        election = get_object_or_404(Election, id=idElection)
        if election.is_open():
            return Response({"error": "L'élection est encore ouverte"}, status=status.HTTP_400_BAD_REQUEST)
        result, created = Resultat.objects.get_or_create(election=election)
        votes = Vote.objects.filter(election=election, electeur__in=[
            u for u in Utilisateur.objects.all() if election.is_voter_allowed(u)
        ], estNul=False)
        result.listeVote.set(votes)
        result.save()
        election.resultat = result
        election.statut = 'ferme'
        election.save()
        logger.info(f"Results published for election {idElection} by {request.user.username}")
        return Response({"message": "Résultats publiés avec succès"}, status=status.HTTP_200_OK)

class UtilisateurCreateAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = UtilisateurCreateSerializer(data=request.data)
        if serializer.is_valid():
            utilisateur = serializer.save()
            logger.info(f"User {request.data['username']} created by {request.user.username}")
            return Response(UtilisateurSerializer(utilisateur).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UtilisateurListAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        utilisateurs = Utilisateur.objects.filter(annee_universitaire=settings.CURRENT_ACADEMIC_YEAR)
        serializer = UtilisateurSerializer(utilisateurs, many=True)
        return Response(serializer.data)

class UtilisateurDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            utilisateur = Utilisateur.objects.get(id=pk)
            if request.user.is_staff or request.user.id == utilisateur.user.id:
                serializer = UtilisateurSerializer(utilisateur)
                return Response(serializer.data)
            return Response({"error": "Accès non autorisé"}, status=status.HTTP_403_FORBIDDEN)
        except Utilisateur.DoesNotExist:
            if request.user.id == int(pk) and request.user.is_staff:
                return Response({
                    'id': request.user.id,
                    'nom': request.user.username,
                    'username': request.user.username,
                    'matricule': '',
                    'annee_universitaire': settings.CURRENT_ACADEMIC_YEAR,
                    'classe': 1,
                    'mention': 'INFO',
                    'activites': [],
                    'sport_type': None,
                    'vote_count': 0,
                    'has_voted': False
                })
            return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, pk):
        try:
            utilisateur = Utilisateur.objects.get(id=pk)
            if not request.user.is_staff:
                return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            serializer = UtilisateurSerializer(utilisateur, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Utilisateur.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, pk):
        try:
            utilisateur = Utilisateur.objects.get(id=pk)
            if not request.user.is_staff:
                return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            utilisateur.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Utilisateur.DoesNotExist:
            return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)

class UtilisateurByUserIdAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        try:
            utilisateur = Utilisateur.objects.get(user__id=user_id)
            if request.user.is_staff or request.user.id == user_id:
                serializer = UtilisateurSerializer(utilisateur)
                return Response(serializer.data)
            return Response({"error": "Accès non autorisé"}, status=status.HTTP_403_FORBIDDEN)
        except Utilisateur.DoesNotExist:
            if request.user.id == user_id and request.user.is_staff:
                return Response({
                    'id': request.user.id,
                    'nom': request.user.username,
                    'username': request.user.username,
                    'matricule': '',
                    'annee_universitaire': settings.CURRENT_ACADEMIC_YEAR,
                    'classe': 1,
                    'mention': 'INFO',
                    'activites': [],
                    'sport_type': None,
                    'vote_count': 0,
                    'has_voted': False
                })
            return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()
            logger.info(f"User {request.user.username} logged out")
            return Response({"message": "Déconnexion réussie"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ElectionResultsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, idElection):
        election = get_object_or_404(Election, id=idElection)
        try:
            utilisateur = Utilisateur.objects.get(user=request.user)
            if not (request.user.is_staff or election.is_voter_allowed(utilisateur)):
                return Response({"error": "Accès non autorisé"}, status=status.HTTP_403_FORBIDDEN)
        except Utilisateur.DoesNotExist:
            if not request.user.is_staff:
                return Response({"error": "Utilisateur non trouvé"}, status=status.HTTP_404_NOT_FOUND)

        # Calculate real-time vote counts
        candidates = [
            {'nom': candidate.nom, 'vote_count': candidate.get_vote_count(election)}
            for candidate in election.listeCandidats.candidats.all()
        ]
        results = {}
        votes = Vote.objects.filter(election=election, estNul=False)
        for vote in votes:
            candidate_name = vote.choix.nom
            results[candidate_name] = results.get(candidate_name, 0) + 1

        data = {
            'election': ElectionSerializer(election, context={'request': request}).data,
            'results': results,
            'candidates': candidates,
            'total_voters': len([u for u in Utilisateur.objects.all() if election.is_voter_allowed(u)]),
            'voters_who_voted': votes.count(),
            'is_published': bool(election.resultat)
        }
        if not request.user.is_staff and not election.resultat:
            return Response({"error": "Les résultats n'ont pas encore été publiés"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)

class ExportElectionsExcelAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        elections = Election.objects.all()
        data = [
            {
                'nom': e.nom,
                'startdate': e.startdate.strftime('%d/%m/%Y %H:%M'),
                'enddate': e.enddate.strftime('%d/%m/%Y %H:%M'),
                'statut': e.statut,
                'voters_who_voted': e.votes.filter(estNul=False).count(),
                'total_voters': len([u for u in Utilisateur.objects.all() if e.is_voter_allowed(u)]),
            }
            for e in elections
        ]
        wb = Workbook()
        ws = wb.active
        ws.title = "Elections"
        headers = ['Nom', 'Date de début', 'Date de fin', 'Statut', 'Votants', 'Électeurs totaux']
        ws.append(headers)
        for row in data:
            ws.append([row['nom'], row['startdate'], row['enddate'], row['statut'], row['voters_who_voted'], row['total_voters']])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            content=output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=elections.xlsx'
        return response

class ExportUsersExcelAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = Utilisateur.objects.all()
        def get_classe_label(classe):
            classes = {1: 'L1', 2: 'L2', 3: 'L3', 4: 'M1', 5: 'M2'}
            return classes.get(classe, 'Inconnu')

        def get_mention_label(mention):
            mentions = {
                'INFO': 'Informatique',
                'SA': 'Sciences Agronomiques',
                'ECO': 'Économie et Commerce',
                'LEA': 'Langues Étrangères Appliquées',
                'ST': 'Sciences de la Terre',
                'DROIT': 'Droit',
            }
            return mentions.get(mention, 'Inconnu')

        def get_activites_label(activites):
            return ', '.join(activite.nom for activite in activites.all()) if activites.exists() else 'N/A'

        data = [
            {
                'nom': u.nom,
                'prenom': u.user.username,
                'classe': get_classe_label(u.classe),
                'mention': get_mention_label(u.mention),
                'activites': get_activites_label(u.activites),
                'sport_type': u.sport_type or 'N/A',
                'annee_universitaire': u.annee_universitaire or 'N/A',
            }
            for u in users
        ]
        wb = Workbook()
        ws = wb.active
        ws.title = "Users"
        headers = ['Nom', 'Prénom', 'Classe', 'Mention', 'Activités', 'Type de sport', 'Année universitaire']
        ws.append(headers)
        for row in data:
            ws.append([
                row['nom'],
                row['prenom'],
                row['classe'],
                row['mention'],
                row['activites'],
                row['sport_type'],
                row['annee_universitaire'],
            ])
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=users.xlsx'
        return response