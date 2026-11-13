"""Interface language support for NIANG IA.

The UI language follows the language configured by the user:
  1. memory/long_term.json        → identity.language.value
  2. memory/installer_profile.json → identity.language.value (before first import)
  3. fallback: French (the base language of the interface)

Interface texts are written in French; tr(text) returns the translation
for the configured language, or the original French text when no
translation exists (or when the configured language is French).
"""

import json
import sys
from pathlib import Path


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"
INSTALLER_PROFILE_PATH = BASE_DIR / "memory" / "installer_profile.json"

# Codes accepted for each UI language. The installer saves the display
# name ("Français", "Wolof", ...), while the LLM memory extractor saves
# English names ("French", ...).
_LANG_ALIASES = {
    "fr": ("fr", "français", "francais", "french"),
    "wo": ("wo", "wolof"),
    "en": ("en", "english", "anglais"),
    "es": ("es", "español", "espanol", "espagnol", "spanish"),
    "ar": ("ar", "arabe", "العربية", "arabic"),
}


def normalize_language(raw) -> str:
    value = str(raw or "").strip().lower()
    if not value:
        return "fr"
    for code, names in _LANG_ALIASES.items():
        if value in names:
            return code
    for code, names in _LANG_ALIASES.items():
        if any(value.startswith(name) for name in names):
            return code
    return "fr"


def _read_configured_language() -> str:
    for path in (MEMORY_PATH, INSTALLER_PROFILE_PATH):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        value = (data.get("identity") or {}).get("language")
        if isinstance(value, dict):
            value = value.get("value")
        code = normalize_language(value)
        if code != "fr":
            return code
    return "fr"


UI_LANGUAGE = _read_configured_language()


def ui_language() -> str:
    """Return the configured UI language code (fr | wo | en | es | ar)."""
    return UI_LANGUAGE


# ── Translations ────────────────────────────────────────────────────────────
# Keys are the exact French strings used in ui.py button texts.

_TR = {
    "en": {
        # Command deck (left)
        "AGENT AUTONOME": "AUTONOMOUS AGENT",
        "DIAGNOSTIC DU PC": "PC DIAGNOSTICS",
        "JEUX DE VISION": "VISION GAMES",
        "RÉSUMÉ DU JOUR": "DAILY BRIEFING",
        "ÉTAT DU SYSTÈME": "SYSTEM STATUS",
        "DÉCRIRE L’ÉCRAN": "DESCRIBE SCREEN",
        "MODE CONCENTRATION": "FOCUS MODE",
        "COUPER LE SON DE L’IA": "MUTE AI AUDIO",
        "RÉACTIVER LE SON DE L’IA": "UNMUTE AI AUDIO",
        "ARRÊTER LE SON DE L’IA": "STOP AI AUDIO",
        # Vision deck (right)
        "APERÇU DE LA CAMÉRA": "CAMERA PREVIEW",
        "CONTRÔLE PAR GESTES": "GESTURE CONTROL",
        "DÉTECTION D’OBJETS": "OBJECT DETECTION",
        "SOURIS GESTUELLE": "AIR MOUSE",
        "VOLUME PAR GESTES": "GESTURE VOLUME",
        "POSTURE": "POSTURE",
        "SUIVI DES MOUVEMENTS": "MOTION TRACKING",
        "DÉMARRER L’ENREGISTREMENT": "START RECORDING",
        "ARRÊTER L’ENREGISTREMENT": "STOP RECORDING",
        "ARRÊTER LA VISION": "STOP VISION",
        "CAPTURER UNE IMAGE": "TAKE SNAPSHOT",
        "COMPTER LES VISAGES": "COUNT FACES",
        "LIRE UN CODE QR": "READ QR CODE",
        "LIRE LE TEXTE": "READ TEXT",
        "SUPPRIMER L’ARRIÈRE-PLAN": "REMOVE BACKGROUND",
        "DÉCRIRE LA SCÈNE": "DESCRIBE SCENE",
        # Agent panel
        "▶ DÉMARRER": "▶ START",
        "■ ARRÊTER": "■ STOP",
        "↻ REPRENDRE": "↻ RESUME",
        "OUVRIR LA CAPTURE": "OPEN SCREENSHOT",
        # PC diagnostics
        "Analyser mon PC": "Analyze my PC",
        "Vérifier les pilotes": "Check drivers",
        "Vérifier Windows": "Check Windows",
        "Diagnostiquer les performances": "Diagnose performance",
        "Détecter les erreurs": "Detect errors",
        "Vérifier le réseau": "Check network",
        "Vérifier les services": "Check services",
        "Vérifier les fichiers système": "Check system files",
        "Proposer des réparations": "Suggest repairs",
        "Historique des diagnostics": "Diagnostics history",
        "Historique des réparations": "Repair history",
        "Arrêter": "Stop",
        "Vider le cache DNS": "Flush DNS cache",
        "Réparer les fichiers système (SFC)": "Repair system files (SFC)",
        "Réparer le magasin Windows (DISM)": "Repair Windows store (DISM)",
        # Vision arcade
        "FILTRE VISAGE": "FACE FILTER",
        "PONG GESTUEL": "GESTURE PONG",
        "CHASSE AUX ORBES": "ORB HUNT",
        "PIERRE-FEUILLE-CISEAUX": "ROCK-PAPER-SCISSORS",
        "CRÉATEUR DE FORMES": "SHAPE CREATOR",
        "LE SOL EST EN LAVE": "FLOOR IS LAVA",
        "EXPLORATEUR PLANÉTAIRE": "PLANET EXPLORER",
        "TOURBILLON": "WHIRLPOOL",
        "DÉFENSE LASER": "LASER DEFENSE",
        "ARPÉGIATEUR": "ARPEGGIATOR",
        # Voice-over studio
        "GÉNÉRER": "GENERATE",
        "▶ LIRE": "▶ PLAY",
        "Ⅱ PAUSE / REPRISE": "Ⅱ PAUSE / RESUME",
        "TÉLÉCHARGER WAV": "DOWNLOAD WAV",
        # Update button
        "↻ MISE À JOUR": "↻ UPDATE",
        "VÉRIFICATION…": "CHECKING…",
        "NIANG IA À JOUR": "NIANG IA UP TO DATE",
        "TÉLÉCHARGEMENT ": "DOWNLOADING ",
        "VERSION ": "VERSION ",
        "INSTALLATEUR PRÊT": "INSTALLER READY",
        # Micro / text-only buttons
        " MUET": " MUTED",
        " EN DIRECT": " LIVE",
        " TEXTE SEUL": " TEXT ONLY",
        " VOIX ACTIVÉE": " VOICE ON",
        # Main input bar
        "EFFACER": "CLEAR",
        "ENVOYER ▸": "SEND ▸",
        # First launch
        "DÉMARRER LE SYSTÈME  ▸": "START SYSTEM  ▸",
    },
    "wo": {
        # Command deck (left)
        "AGENT AUTONOME": "AJAN OTONOM",
        "DIAGNOSTIC DU PC": "DIAGNOSTIKU PC",
        "JEUX DE VISION": "JEU YU VIZION",
        "RÉSUMÉ DU JOUR": "XIBAR YU BÉSS",
        "ÉTAT DU SYSTÈME": "XAALU SISTEEM",
        "DÉCRIRE L’ÉCRAN": "WERENTE EKRAN",
        "MODE CONCENTRATION": "MODU KONSANTRASYON",
        "COUPER LE SON DE L’IA": "SËDD SONU IA",
        "RÉACTIVER LE SON DE L’IA": "DEGGALI SONU IA",
        "ARRÊTER LE SON DE L’IA": "DËDDU SONU IA",
        # Vision deck (right)
        "APERÇU DE LA CAMÉRA": "GIS KAMÉRA",
        "CONTRÔLE PAR GESTES": "KONTROL CI LOXO",
        "DÉTECTION D’OBJETS": "GÉNÉ OBJÉ",
        "SOURIS GESTUELLE": "SOURIS CI LOXO",
        "VOLUME PAR GESTES": "VOLUME CI LOXO",
        "POSTURE": "POSTUR",
        "SUIVI DES MOUVEMENTS": "TOPPATO MOUVMAN YI",
        "DÉMARRER L’ENREGISTREMENT": "TAMBALI REYISTRE",
        "ARRÊTER L’ENREGISTREMENT": "DËDDU REYISTRE",
        "ARRÊTER LA VISION": "DËDDU VIZION",
        "CAPTURER UNE IMAGE": "JAPP PIKTIR",
        "COMPTER LES VISAGES": "MËT KANAM YI",
        "LIRE UN CODE QR": "JÀNG QR KOD",
        "LIRE LE TEXTE": "JÀNG TÈKS",
        "SUPPRIMER L’ARRIÈRE-PLAN": "FAR ARRIÈRE-PLAN",
        "DÉCRIRE LA SCÈNE": "WERENTE SCÈN",
        # Agent panel
        "▶ DÉMARRER": "▶ TAMBALI",
        "■ ARRÊTER": "■ DËDDU",
        "↻ REPRENDRE": "↻ JOKKO",
        "OUVRIR LA CAPTURE": "UBBIKIL PIKTIR",
        # PC diagnostics
        "Analyser mon PC": "Analize PC bi",
        "Vérifier les pilotes": "Xaar pilote yi",
        "Vérifier Windows": "Xaar Windows",
        "Diagnostiquer les performances": "Diagnostiku performans yi",
        "Détecter les erreurs": "Géné erreur yi",
        "Vérifier le réseau": "Xaar rézo bi",
        "Vérifier les services": "Xaar servis yi",
        "Vérifier les fichiers système": "Xaar fisye sistëm yi",
        "Proposer des réparations": "Tere réparasyon yi",
        "Historique des diagnostics": "Liste diagnostik yi",
        "Historique des réparations": "Liste réparasyon yi",
        "Arrêter": "Dëddu",
        "Vider le cache DNS": "Far cache DNS",
        "Réparer les fichiers système (SFC)": "Deggali fisye yi (SFC)",
        "Réparer le magasin Windows (DISM)": "Deggali magasin Windows (DISM)",
        # Vision arcade
        "FILTRE VISAGE": "FILTE KANAM",
        "PONG GESTUEL": "PONG CI LOXO",
        "CHASSE AUX ORBES": "GÉNN ORBE YI",
        "PIERRE-FEUILLE-CISEAUX": "PIERRE-FEUILLE-CISEAUX",
        "CRÉATEUR DE FORMES": "DEFAR FORME YI",
        "LE SOL EST EN LAVE": "SUUF LA LAVA",
        "EXPLORATEUR PLANÉTAIRE": "XALAB PLANÈT YI",
        "TOURBILLON": "TOURBILLON",
        "DÉFENSE LASER": "DEFANS LASER",
        "ARPÉGIATEUR": "ARPEJATOR",
        # Voice-over studio
        "GÉNÉRER": "DEFAR",
        "▶ LIRE": "▶ JÀNG",
        "Ⅱ PAUSE / REPRISE": "Ⅱ PAUSE / JOKKO",
        "TÉLÉCHARGER WAV": "YEBBI WAV",
        # Update button
        "↻ MISE À JOUR": "↻ SOPPI",
        "VÉRIFICATION…": "XAAR…",
        "NIANG IA À JOUR": "NIANG IA SOPPI NA",
        "TÉLÉCHARGEMENT ": "YEBBI ",
        "VERSION ": "VERSION ",
        "INSTALLATEUR PRÊT": "INSTALLATEUR PRÊT",
        # Micro / text-only buttons
        " MUET": " MUUT",
        " EN DIRECT": " DIRËKT",
        " TEXTE SEUL": " TÈKS REK",
        " VOIX ACTIVÉE": " VOIX AKTIF",
        # Main input bar
        "EFFACER": "FAR",
        "ENVOYER ▸": "YÓNNEE ▸",
        # First launch
        "DÉMARRER LE SYSTÈME  ▸": "TAMBALI SISTEEM  ▸",
    },
    "es": {
        # Command deck (left)
        "AGENT AUTONOME": "AGENTE AUTÓNOMO",
        "DIAGNOSTIC DU PC": "DIAGNÓSTICO DEL PC",
        "JEUX DE VISION": "JUEGOS DE VISIÓN",
        "RÉSUMÉ DU JOUR": "RESUMEN DEL DÍA",
        "ÉTAT DU SYSTÈME": "ESTADO DEL SISTEMA",
        "DÉCRIRE L’ÉCRAN": "DESCRIBIR LA PANTALLA",
        "MODE CONCENTRATION": "MODO CONCENTRACIÓN",
        "COUPER LE SON DE L’IA": "SILENCIAR LA IA",
        "RÉACTIVER LE SON DE L’IA": "REACTIVAR LA IA",
        "ARRÊTER LE SON DE L’IA": "DETENER EL SONIDO DE LA IA",
        # Vision deck (right)
        "APERÇU DE LA CAMÉRA": "VISTA PREVIA DE LA CÁMARA",
        "CONTRÔLE PAR GESTES": "CONTROL POR GESTOS",
        "DÉTECTION D’OBJETS": "DETECCIÓN DE OBJETOS",
        "SOURIS GESTUELLE": "RATÓN GESTUAL",
        "VOLUME PAR GESTES": "VOLUMEN POR GESTOS",
        "POSTURE": "POSTURA",
        "SUIVI DES MOUVEMENTS": "SEGUIMIENTO DE MOVIMIENTOS",
        "DÉMARRER L’ENREGISTREMENT": "INICIAR GRABACIÓN",
        "ARRÊTER L’ENREGISTREMENT": "DETENER GRABACIÓN",
        "ARRÊTER LA VISION": "DETENER LA VISIÓN",
        "CAPTURER UNE IMAGE": "CAPTURAR UNA IMAGEN",
        "COMPTER LES VISAGES": "CONTAR LOS ROSTROS",
        "LIRE UN CODE QR": "LEER UN CÓDIGO QR",
        "LIRE LE TEXTE": "LEER EL TEXTO",
        "SUPPRIMER L’ARRIÈRE-PLAN": "QUITAR EL FONDO",
        "DÉCRIRE LA SCÈNE": "DESCRIBIR LA ESCENA",
        # Agent panel
        "▶ DÉMARRER": "▶ INICIAR",
        "■ ARRÊTER": "■ DETENER",
        "↻ REPRENDRE": "↻ REANUDAR",
        "OUVRIR LA CAPTURE": "ABRIR LA CAPTURA",
        # PC diagnostics
        "Analyser mon PC": "Analizar mi PC",
        "Vérifier les pilotes": "Verificar los controladores",
        "Vérifier Windows": "Verificar Windows",
        "Diagnostiquer les performances": "Diagnosticar el rendimiento",
        "Détecter les erreurs": "Detectar errores",
        "Vérifier le réseau": "Verificar la red",
        "Vérifier les services": "Verificar los servicios",
        "Vérifier les fichiers système": "Verificar archivos del sistema",
        "Proposer des réparations": "Proponer reparaciones",
        "Historique des diagnostics": "Historial de diagnósticos",
        "Historique des réparations": "Historial de reparaciones",
        "Arrêter": "Detener",
        "Vider le cache DNS": "Vaciar la caché DNS",
        "Réparer les fichiers système (SFC)": "Reparar archivos del sistema (SFC)",
        "Réparer le magasin Windows (DISM)": "Reparar el almacén de Windows (DISM)",
        # Vision arcade
        "FILTRE VISAGE": "FILTRO DE ROSTRO",
        "PONG GESTUEL": "PONG GESTUAL",
        "CHASSE AUX ORBES": "CAZA DE ORBES",
        "PIERRE-FEUILLE-CISEAUX": "PIEDRA-PAPEL-TIJERA",
        "CRÉATEUR DE FORMES": "CREADOR DE FORMAS",
        "LE SOL EST EN LAVE": "EL SUELO ES LAVA",
        "EXPLORATEUR PLANÉTAIRE": "EXPLORADOR PLANETARIO",
        "TOURBILLON": "REMOLINO",
        "DÉFENSE LASER": "DEFENSA LÁSER",
        "ARPÉGIATEUR": "ARPEGIADOR",
        # Voice-over studio
        "GÉNÉRER": "GENERAR",
        "▶ LIRE": "▶ REPRODUCIR",
        "Ⅱ PAUSE / REPRISE": "Ⅱ PAUSA / REANUDAR",
        "TÉLÉCHARGER WAV": "DESCARGAR WAV",
        # Update button
        "↻ MISE À JOUR": "↻ ACTUALIZAR",
        "VÉRIFICATION…": "VERIFICANDO…",
        "NIANG IA À JOUR": "NIANG IA ACTUALIZADO",
        "TÉLÉCHARGEMENT ": "DESCARGA ",
        "VERSION ": "VERSIÓN ",
        "INSTALLATEUR PRÊT": "INSTALADOR LISTO",
        # Micro / text-only buttons
        " MUET": " SILENCIADO",
        " EN DIRECT": " EN VIVO",
        " TEXTE SEUL": " SOLO TEXTO",
        " VOIX ACTIVÉE": " VOZ ACTIVADA",
        # Main input bar
        "EFFACER": "BORRAR",
        "ENVOYER ▸": "ENVIAR ▸",
        # First launch
        "DÉMARRER LE SYSTÈME  ▸": "INICIAR EL SISTEMA  ▸",
    },
    "ar": {
        # Command deck (left)
        "AGENT AUTONOME": "الوكيل المستقل",
        "DIAGNOSTIC DU PC": "تشخيص الحاسوب",
        "JEUX DE VISION": "ألعاب الرؤية",
        "RÉSUMÉ DU JOUR": "ملخص اليوم",
        "ÉTAT DU SYSTÈME": "حالة النظام",
        "DÉCRIRE L’ÉCRAN": "وصف الشاشة",
        "MODE CONCENTRATION": "وضع التركيز",
        "COUPER LE SON DE L’IA": "كتم صوت الذكاء الاصطناعي",
        "RÉACTIVER LE SON DE L’IA": "إعادة تشغيل صوت الذكاء الاصطناعي",
        "ARRÊTER LE SON DE L’IA": "إيقاف صوت الذكاء الاصطناعي",
        # Vision deck (right)
        "APERÇU DE LA CAMÉRA": "معاينة الكاميرا",
        "CONTRÔLE PAR GESTES": "التحكم بالإيماءات",
        "DÉTECTION D’OBJETS": "اكتشاف الأجسام",
        "SOURIS GESTUELLE": "فأرة جوية",
        "VOLUME PAR GESTES": "مستوى الصوت بالإيماءات",
        "POSTURE": "الوضعية",
        "SUIVI DES MOUVEMENTS": "تتبع الحركات",
        "DÉMARRER L’ENREGISTREMENT": "بدء التسجيل",
        "ARRÊTER L’ENREGISTREMENT": "إيقاف التسجيل",
        "ARRÊTER LA VISION": "إيقاف الرؤية",
        "CAPTURER UNE IMAGE": "التقاط صورة",
        "COMPTER LES VISAGES": "عدّ الوجوه",
        "LIRE UN CODE QR": "قراءة رمز QR",
        "LIRE LE TEXTE": "قراءة النص",
        "SUPPRIMER L’ARRIÈRE-PLAN": "إزالة الخلفية",
        "DÉCRIRE LA SCÈNE": "وصف المشهد",
        # Agent panel
        "▶ DÉMARRER": "▶ بدء",
        "■ ARRÊTER": "■ إيقاف",
        "↻ REPRENDRE": "↻ استئناف",
        "OUVRIR LA CAPTURE": "فتح الصورة",
        # PC diagnostics
        "Analyser mon PC": "تحليل حاسوبي",
        "Vérifier les pilotes": "فحص التعريفات",
        "Vérifier Windows": "فحص Windows",
        "Diagnostiquer les performances": "تشخيص الأداء",
        "Détecter les erreurs": "كشف الأخطاء",
        "Vérifier le réseau": "فحص الشبكة",
        "Vérifier les services": "فحص الخدمات",
        "Vérifier les fichiers système": "فحص ملفات النظام",
        "Proposer des réparations": "اقتراح إصلاحات",
        "Historique des diagnostics": "سجل التشخيصات",
        "Historique des réparations": "سجل الإصلاحات",
        "Arrêter": "إيقاف",
        "Vider le cache DNS": "مسح ذاكرة DNS المؤقتة",
        "Réparer les fichiers système (SFC)": "إصلاح ملفات النظام (SFC)",
        "Réparer le magasin Windows (DISM)": "إصلاح مخزن Windows (DISM)",
        # Vision arcade
        "FILTRE VISAGE": "فلتر الوجه",
        "PONG GESTUEL": "بونغ بالإيماءات",
        "CHASSE AUX ORBES": "صيد الكرات",
        "PIERRE-FEUILLE-CISEAUX": "حجر ورقة مقص",
        "CRÉATEUR DE FORMES": "منشئ الأشكال",
        "LE SOL EST EN LAVE": "الأرض حمم",
        "EXPLORATEUR PLANÉTAIRE": "مستكشف الكواكب",
        "TOURBILLON": "دوامة",
        "DÉFENSE LASER": "دفاع الليزر",
        "ARPÉGIATEUR": "عازف الأربيجيو",
        # Voice-over studio
        "GÉNÉRER": "توليد",
        "▶ LIRE": "▶ تشغيل",
        "Ⅱ PAUSE / REPRISE": "Ⅱ إيقاف مؤقت / استئناف",
        "TÉLÉCHARGER WAV": "تنزيل WAV",
        # Update button
        "↻ MISE À JOUR": "↻ تحديث",
        "VÉRIFICATION…": "جارٍ التحقق…",
        "NIANG IA À JOUR": "NIANG IA محدَّث",
        "TÉLÉCHARGEMENT ": "تنزيل ",
        "VERSION ": "الإصدار ",
        "INSTALLATEUR PRÊT": "المُثبِّت جاهز",
        # Micro / text-only buttons
        " MUET": " صامت",
        " EN DIRECT": " مباشر",
        " TEXTE SEUL": " نص فقط",
        " VOIX ACTIVÉE": " الصوت مفعّل",
        # Main input bar
        "EFFACER": "مسح",
        "ENVOYER ▸": "إرسال ▸",
        # First launch
        "DÉMARRER LE SYSTÈME  ▸": "تشغيل النظام  ▸",
    },
}


def tr(text: str) -> str:
    """Translate a French UI string into the configured language."""
    table = _TR.get(UI_LANGUAGE)
    if not table:
        return text
    return table.get(text, text)
