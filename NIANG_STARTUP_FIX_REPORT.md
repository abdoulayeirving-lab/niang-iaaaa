# NIANG IA STARTUP FIX REPORT

## 1. Audit du script de démarrage actuel

### 1.1 Fichier analysé : START_NIANG_IA.bat

Le script principal effectue ces actions :
- Définit le jeu de caractères UTF-8 (chcp 65001)
- Se place dans le répertoire du script (cd /d "%~dp0")
- Définit le titre de la fenêtre (title NIANG IA - Assistant)
- **Cherche ou installe Python 3.11/3.12** :
  - `.venv\Scripts\python.exe` (environnement virtuel)
  - `py -3.12` / `py -3.11` (Python Launcher for Windows)
  - Chemins système `%LocalAppData%\Programs\Python\Python312\python.exe`
  - Installation automatique via `winget install Python.Python.3.12`
- **Crée l'environnement virtuel** si nécessaire (`python -m venv .venv`)
- **Installe les dépendances** (`setup.py`)
- **Lance l'application** : `"%PYTHON_EXE%" main.py`

## 2. Cause racine de l'apparition de CMD

- `python.exe` est conçu pour exécuter des scripts avec une console attachée
- Exécuter `python.exe main.py` crée une nouvelle fenêtre console sous Windows
- Cela se produit indépendamment du fait que le script soit une application GUI ou non
- Les toolkits GUI (`tkinter`, `PyQt`, `pywinauto`, etc.) fonctionnent parfaitement dans ce contexte, mais la fenêtre console elle-même est visible

## 3. Méthode de lancement identifiée

Le fichier batch vérifie Python dans cet ordre :
1. `.venv\Scripts\python.exe` (environnement virtuel)
2. `py -3.12` ou `py -3.11` (Python Launcher for Windows)
3. `%LocalAppData%\Programs\Python\Python312\python.exe` ou Python311
4. `python` depuis PATH
5. Installation automatique via `winget install Python.Python.3.12`

La variable `%PYTHON_EXE%` est définie sur quel que soit l'interpréteur Python trouvé en premier.

## 5. Corrections à apporter

Utiliser `pythonw.exe` au lieu de `python.exe` pour éliminer la fenêtre console.

- `pythonw.exe` est un lanceur Python qui exécute des scripts sans créer de fenêtre console
- Il est inclus avec toutes les installations Python (dans le répertoire `...\PythonXX\`)
- Les applications GUI (`tkinter`, `PyQt`, `pywinauto`, etc.) fonctionnent parfaitement avec `pythonw.exe`
- **Important** : `pythonw.exe` ne capture pas stdout/stderr par défaut. Il faut rediriger vers des fichiers journaux.

## 7. Modification de START_NIANG_IA.bat

Remplacer la ligne de lancement :
```
"%PYTHON_EXE%" main.py
```
par :
```
where pythonw >nul 2>&1 && (
    %APPDATA%\..\Local\Programs\Python\Python312\pythonw.exe main.py
) || (
    "%PYTHON_EXE%" main.py
)
```

## 10. Redirection des journaux (critical pour pythonw.exe)

Puisque `pythonw.exe` ne montre pas de fenêtre console, il faut rediriger la sortie vers des fichiers journaux. Modifier `main.py` pour rediriger stdout/stderr dès le début :

```python
import os

# Créer le répertoire logs s'il n'existe pas
os.makedirs("logs", exist_ok=True)

# Rediriger stdout et stderr vers des fichiers AVANT toute autre sortie
import atexit

class LogFile:
    def __init__(self, filename):
        self.file = open(filename, 'a', encoding='utf-8')
    
    def write(self, message):
        self.file.write(message)
    
    def flush(self):
        self.file.flush()

# Rediriger stdout et stderr
stdout_logger = LogFile("logs/niang_ia_stdout.log")
stderr_logger = LogFile("logs/niang_ia_stderr.log")
old_stdout = sys.stdout
old_stderr = sys.stderr
sys.stdout = stdout_logger
sys.stderr = stderr_logger

# S'assurer que les fichiers de log sont fermés à la fin
atexit.register(lambda: (stdout_logger.file.close(), stderr_logger.file.close()))
```

## 11. Vérification du fonctionnement avec pythonw.exe

**À vérifier impérativement** :
- [ ] GUI apparaît normalement et immédiatement
- [ ] Sphère interactive et animations fonctionnent
- [ ] Microphone et système vocal fonctionnent
- [ ] Tous les modules existants continuent de fonctionner
- [ ] NIANG IA reste dans la barre des tâches
- [ ] Aucune fenêtre console n'apparait
- [ ] Aucune fenêtre PowerShell n'apparait
- [ ] L'application ne crée pas plusieurs instances

## 10. Plan d'implémentation

### Phase 1 : Modifier START_NIANG_IA.bat

Remplacer la section de lancement par le code ci-dessus.

### Phase 2 : Modifier main.py

Ajouter la redirection de journaux au tout début du fichier, avant toute autre sortie.

### Phase 3 : Tester le démarrage sur Windows 11

Vérifier la liste de vérification ci-dessus.

### 11. Plan de rollback

Si la correction cause des problèmes :
- Restaurer START_NIANG_IA.bat à l'état original
- Restaurer main.py en enlevant la redirection de journaux
- Supprimer le répertoire logs/
- Tester le démarrage d'origine confirme le retour de la fenêtre CMD

## 12. Conclusion

La correction utilisant `pythonw.exe` est la méthode standard pour lancer des applications Python GUI sans fenêtre console. Avec la redirection de journaux adéquate dans `main.py`, toute la sortie sera capturée dans des fichiers journaux, maintenant la capacité de débogage tout en maintenant une interface utilisateur propre.

**Essentiel** :
1. `pythonw.exe` pour lancement sans console
2. Redirection de journaux dans `main.py` pour capturer stdout/stderr
3. Vérification que toutes les fonctionnalités NIANG IA fonctionnent toujours