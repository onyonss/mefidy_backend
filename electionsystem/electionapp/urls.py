from django.urls import path
from . import api_views

urlpatterns = [
    path('api/login/', api_views.LoginAPIView.as_view(), name='login'),
    path('api/logout/', api_views.LogoutAPIView.as_view(), name='logout'),
    path('api/first-login/', api_views.FirstLoginAPIView.as_view(), name='first-login'),
    path('api/users/import/', api_views.UserImportAPIView.as_view(), name='user-import'),
    path('api/elections/', api_views.ElectionListCreateAPIView.as_view(), name='election-list-create'),
    path('api/elections/<int:idElection>/', api_views.ElectionDetailAPIView.as_view(), name='election-detail'),
    path('api/elections/<int:idElection>/vote/', api_views.VoterAPIView.as_view(), name='vote'),
    path('api/elections/<int:idElection>/resultats/', api_views.ElectionResultsAPIView.as_view(), name='election-results'),
    path('api/elections/<int:idElection>/publier/', api_views.PublierResultatsAPIView.as_view(), name='election-publish'),
    path('api/users/', api_views.UtilisateurListAPIView.as_view(), name='user-list'),
    path('api/users/<int:pk>/', api_views.UtilisateurDetailAPIView.as_view(), name='user-detail'),
    path('api/users/by-user-id/<int:user_id>/', api_views.UtilisateurByUserIdAPIView.as_view(), name='user-by-user-id'),
    path('api/users/create/', api_views.UtilisateurCreateAPIView.as_view(), name='user-create'),
    path('api/listecandidats/', api_views.ListeCandidatsListAPIView.as_view(), name='listecandidats-list'),
    path('api/listecandidats/create/', api_views.ListeCandidatsCreateAPIView.as_view(), name='listecandidats-create'),
    path('api/fingerprint/verify/', api_views.FingerprintVerifyAPIView.as_view(), name='fingerprint-verify'),
    path('api/token/', api_views.CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/elections/export-excel/', api_views.ExportElectionsExcelAPIView.as_view(), name='export-elections-excel'),
    path('api/users/export-excel/', api_views.ExportUsersExcelAPIView.as_view(), name='export-users-excel'),
]