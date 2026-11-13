# whatsapp_monitor.py — NIANG IA Surveillance WhatsApp Desktop (MODE SUR DEMANDE)
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import psutil
from pywinauto import Desktop, Application
from pywinauto.find import ElementNotFoundError

from memory.memory_manager import load_memory, update_memory, should_extract_memory, extract_memory

# Configuration
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_PATH = CONFIG_DIR / "app_settings.json"
WHATSAPP_PROCESS_NAME = "WhatsApp.exe"
NEW_MESSAGE_WINDOW_SECONDS = 30
MAX_CONVERSATIONS_KEPT = 50
DEFAULT_SETTINGS = {
    "whatsapp_monitoring_enabled": False,
    "whatsapp_silence_mode": False,
}

# Logging
logger = logging.getLogger("niang_whatsapp_monitor")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[WhatsAppMonitor] %(levelname)s: %(message)s"))
logger.addHandler(handler)
#──────────────────────────────────────────────────────────────────────────────
# Classe principale WhatsAppMonitor (MODE SUR DEMANDE)
#──────────────────────────────────────────────────────────────────────────────
class WhatsAppMonitor:
    """Surveille WhatsApp Desktop via Windows UI Automation (mode sur demande)."""
    
    def __init__(self) → None:
        self._last_checked_messages: Dict[str, float] = {}
        self._known_messages: Set[str] = set()
        self._conversation_history: deque = deque(maxlen=MAX_CONVERSATIONS_KEPT)
        self._settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._silence_mode: bool = False
        self._callbacks: Dict[str, callable] = {
            "on_new_message": lambda msg: None,
            "on_status_change": lambda status: None,
        }
        self._load_settings()
        logger.info("WhatsAppMonitor initialisé (surveillance désactivée par défaut)")
    
    def _load_settings(self) → None:
        try:
            if SETTINGS_PATH.is_file():
                import json
                loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    for key in DEFAULT_SETTINGS:
                        if key in loaded:
                            self._settings[key] = loaded[key]
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Impossible de charger les paramètres : {e}")
        self._silence_mode = self._settings.get("whatsapp_silence_mode", False)
    
    def _save_settings(self) → None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            patch = {
                "whatsapp_monitoring_enabled": self._settings.get("whatsapp_monitoring_enabled", False),
                "whatsapp_silence_mode": self._settings.get("whatsapp_silence_mode", False),
            }
            SETTINGS_PATH.write_text(
                json.dumps(patch, indent=2, ensure_ascii=False), encoding="utf-8"
            )
# ── Détection de WhatsApp ──────────────────────────────────────────────
    
# ── Vérification sur demande ───────────────────────────────────────────
    
    def check_messages(self) → Dict[str, Any]:
        """
        Vérifier les nouveaux messages WhatsApp (déclenché sur demande).
        
        Returns:
            Dict avec l'état de la vérification
        """
        logger.info("Vérification des messages WhatsApp sur demande")
        
        # 1. WhatsApp est-il ouvert ?
        if not self.is_whatsapp_open():
            self._callbacks["on_status_change"]("déconnecté")
            return {
                "nouveaux_messages": 0,
                "dernier_expéditeur": None,
                "statut": "whatsapp_non_ouvert",
            }
    def is_whatsapp_open(self) → bool:
        """Vérifier si WhatsApp Desktop est en cours d'exécution."""
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == WHATSAPP_PROCESS_NAME.lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
    
    # ── Vérification sur demande ───────────────────────────────────────────
        except OSError as e:
            logger.warning(f"Impossible de sauvegarder les paramètres : {e}")
    
    # ── Détection de WhatsApp ──────────────────────────────────────────────
# 3. Traverser les éléments accessibles
        try:
            conversations = self._extract_conversations(main_window)
        except Exception as e:
            logger.error(f"Erreur extraction conversations : {e}")
            return {
                "nouveaux_messages": 0,
                "dernier_expéditeur": None,
                "statut": "erreur_extraction",
            }
        
        if not conversations:
            self._callbacks["on_status_change"]("aucun_message")
            return {
                "nouveaux_messages": 0,
                "dernier_expéditeur": None,
                "statut": "aucun_message",
            }
    
    # ── Extraction des conversations ──────────────────────────────────────
# ── Extraction des conversations ──────────────────────────────────────
    
    def _extract_conversations(self, main_window: Any) → List[Tuple[str, str, float]]:
        """
        Extraire la liste des conversations (contact, message, timestamp)
        depuis la fenêtre WhatsApp via UI Automation.
        
        Returns : Liste de tuples (contact_name, message_text, timestamp_unix)
        """
        conversations: List[Tuple[str, str, float]] = []
        
        try:
            # Essayer de trouver la liste des chats/conversations
            # La structure UI d'WhatsApp Desktop peut varier, on essaie plusieurs approches
            
            # Approche 1 : Rechercher les éléments de type "pane" ou "wrapper" contenant les chats
            try:
                chat_elements = main_window.descendants(
                    found_index=0,
                    control_type="Pane",
                )
            except Exception:
                chat_elements = []
            
            # Si pas trouvé, chercher par titre ou classe
            if not chat_elements:
                try:
                    chat_elements = main_window.descendants(
                        found_index=0,
                        automation_id="chat_list",
                    )
                except Exception:
                    chat_elements = []
            
            # Parcourir les éléments trouvés
            for elem in chat_elements[:30]:  # Limite de sécurité
                try:
                    # Essayer d'obtenir le nom du contact
                    contact_name = self._get_text(elem)
                    if not contact_name or contact_name.lower() in {"whatsapp", "chat"}:
                        continue
                    
                    # Essayer d'obtenir le dernier message
                    last_msg = self._get_last_message(elem)
# ── Mise à jour mémoire ────────────────────────────────────────────────
    
    def _update_memory_for_contact(self, contact_name: str, message_text: str) → None:
        """Mettre à jour la mémoire à court terme avec un nouveau contact/msg."""
        try:
            # Essayer d'extraire de la mémoire si pertinent
            if should_extract_memory(message_text):
                extract_memory(message_text, contact_name)
            
            # Mettre à jour la mémoire à long terme avec le contact
            memory = load_memory()
            contact_lower = contact_name.lower()
            
            if contact_lower not in memory:
                memory[contact_lower] = {
                    "first_seen": time.time(),
                    "last_seen": time.time(),
                    "message_count": 0,
                    "last_message": "",
                }
# ── Utilitaires publics ─────────────────────────────────────────────────

    def is_whatsapp_open(self) → bool:
        """Vérifier si WhatsApp Desktop est en cours d'exécution."""
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == WHATSAPP_PROCESS_NAME.lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
    
    def get_last_sender(self) → Optional[str]:
        """Retourner le dernier expéditeur détecté."""
        if self._conversation_history:
            last = self._conversation_history[-1]
            return last["contact"]
        return None
    
    def get_new_messages_count(self) → int:
        """Compter les messages non lus/récents."""
        current_time = time.time()
        count = 0
        for contact, msg_ts in self._last_checked_messages.items():
            if current_time - msg_ts < NEW_MESSAGE_WINDOW_SECONDS:
                count += 1
        return count
    
    def get_status(self) → Dict[str, Any]:
        """Retourner l'état actuel du surveillant."""
        return {
            "surveillance_active": False,  # Toujours False en mode sur demande
            "whatsapp_ouvert": self.is_whatsapp_open(),
            "silence_mode": self._silence_mode,
            "nouveaux_messages": self.get_new_messages_count(),
            "dernier_expéditeur": self.get_last_sender(),
            "conversations_memorisees": len(self._conversation_history),
        }
    
    def format_message_for_voice(self, message: Dict[str, Any]) → str:
        """Formatter un message pour la sortie vocale."""
        contact = message.get("contact", "Inconnu")
        text = message.get("message", "")
        timestamp = message.get("timestamp", 0)
        
        horodatage = time.strftime("à %H:%M:%S", time.localtime(timestamp)) if timestamp else ""
        
        return f"Message de {contact} {horodatage} : {text}"
            
            memory[contact_lower]["last_seen"] = time.time()
            memory[contact_lower]["message_count"] = memory.get(contact_lower, {}).get("message_count", 0) + 1
            memory[contact_lower]["last_message"] = message_text[:100]  # Premier extrait
            
            # Nettoyer le message de toute info sensible avant stockage
            update_memory(memory)
            
        except Exception as e:
            logger.warning(f"Impossible de mettre à jour la mémoire : {e}")
    
    # ── Utilitaires publics ─────────────────────────────────────────────────
                    if last_msg:
                        conversations.append((contact_name, last_msg, time.time()))
                
                except Exception:
                    continue
        
        return conversations
    
    def _get_text(self, element: Any) → str:
        """Extraire le texte d'un élément UI Automation, retour vide en cas d'erreur."""
        try:
            return element.window_text().strip()
        except Exception:
            try:
                return element.name.strip()
            except Exception:
                return ""
    
    def _get_last_message(self, container: Any) → Optional[str]:
        """Extraire le dernier message d'un conteneur de conversation."""
        try:
            message_elements = container.descendants(
                found_index=0,
                class_name="RichTextControl",
            ) or container.descendants(found_index=0, control_type="Text")
            
            if message_elements:
                for msg_elem in reversed(message_elements):
                    text = self._get_text(msg_elem).strip()
                    if text and text.lower() not in {"whatsapp", "message"}:
                        return text[:200]  # Limiter la longueur
        except Exception:
            pass
        return None
    
    # ── Mise à jour mémoire ────────────────────────────────────────────────