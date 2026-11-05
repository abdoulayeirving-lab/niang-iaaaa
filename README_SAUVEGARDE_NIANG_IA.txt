SAUVEGARDE NIANG IA 1.0.24
==========================

Le fichier NIANG_IA_1.0.24.nia contient une copie chiffree de NIANG IA,
y compris sa configuration privee, ses cles API et sa memoire.

Gardez ce fichier et le script RESTAURER_NIANG_IA.ps1 ensemble. Conservez le
mot de passe separement : sans lui, la sauvegarde ne peut pas etre restauree.
Le mot de passe n'est pas stocke dans ces fichiers.

Pour restaurer la copie, ouvrez PowerShell dans ce dossier et lancez :

  powershell -ExecutionPolicy Bypass -File .\RESTAURER_NIANG_IA.ps1

Une fenetre vous demandera le mot de passe. La restauration cree
%USERPROFILE%\Downloads\NIANG_IA_1.0.24_Restored\NIANG_IA.
Lancez START_NIANG_IA.bat dans ce dossier pour demarrer l'application.

Le dossier restaure n'est pas chiffre. Ne le laissez pas sur un ordinateur
partage et supprimez-le lorsque vous n'en avez plus besoin.
