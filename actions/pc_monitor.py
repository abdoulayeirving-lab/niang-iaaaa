# pc_monitor.py — NIANG IA Surveillance intelligente du PC
# Import des modules du projet NIANG IA
class PCMonitor:
    def __init__(self):
        self.last_update = time.time()
    
    def get_system(self):
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        try:
            import platform
            return {"os": f"{platform.system()} {platform.release()}", "processor": platform.processor() or "Inconnu"}
        except:
            return {"error": "inconnu"}
def get_system_info(self):
        """Retourne les informations de base sur le système d'exploitation."""
def get_cpu_info(self):
        """Retourne les informations détaillées sur le processeur."""
def get_gpu_info(self):
        """Retourne les informations sur la carte graphique disponible."""
def get_ram_info(self):
        """Retourne les informations détaillées sur la mémoire système."""
def get_disk_info(self, drive="C"):
        """Retourne les informations sur les disques durs/SSD."""
def get_battery_info(self):
        """Retourne les informations sur la batterie (portables)."""
def get_network_info(self):
        """Retourne les informations de connexion réseau."""
def get_overall_status(self):
        """Retourne un statut global avec détection de problèmes."""
# Fonctions utilitaires pour l'intégration vocale

def format_status_for_voice(status_dict):
    """Formate le statut système en langage naturel pour la voix."""
    try:
        lines = []
        
        # CPU
        cpu = status_dict.get("cpu", {})
        cpu_name = cpu.get("name", "Processeur")
        cpu_usage = cpu.get("usage_percent", 0)
        lines.append(f"Processeur {cpu_name} {cpu_usage}% d'utilisation")
        
        # RAM
        ram = status_dict.get("ram", {})
        ram_percent = ram.get("percent_used", 0)
        lines.append(f"Mémoire {ram_percent}% utilisée")
        
        # Disque
        disks = status_dict.get("disks", {})
        if disks.get("disks"):
            disk = disks["disks"][0]  # Premier disque
            disk_percent = disk.get("percent_used", 0)
            lines.append(f"Disque {disk_percent}% plein")
        
        # Problèmes
        problems = status_dict.get("problems_found", [])
        if problems:
            lines.append(f"{len(problèmes)} problème{'s' if len(problems) > 1 else ''} détecté{'s' if len(problems) > 1 else ''}")
        
        return " | ".join(lines) if lines else "Statut système disponible"
    except:
        return "Impossible de formater le statut"

def get_simple_health_check():
    """Vérification rapide de santé pour commandes vocales."""
    monitor = get_monitor()
    try:
        overall = monitor.get_overall_status()
        cpu = overall.get("cpu", {})
        ram = overall.get("ram", {})
        
        cpu_usage = cpu.get("usage_percent", 0)
        ram_usage = ram.get("percent_used", 0)
        temp = cpu.get("temperature", "Non disponible")
        
        return {
            "cpu_percent": cpu_usage,
            "ram_percent": ram_usage,
            "cpu_temperature": temp,
            "is_healthy": cpu_usage < 80 and ram_usage < 85
        }
    except:
        return {"cpu_percent": 0, "ram_percent": 0, "cpu_temperature": "Erreur", "is_healthy": False}

# Point d'entrée pour test direct
if __name__ == "__main__":
    print("=== NIANG IA PC Monitor ===")
    monitor = PCMonitor()
    
    print("\n1. Informations système:")
    print(json.dumps(monitor.get_system_info(), indent=2, ensure_ascii=False))
    
    print("\n2. Processeur:")
    print(json.dumps(monitor.get_cpu_info(), indent=2, ensure_ascii=False))
    
    print("\n3. Mémoire RAM:")
    print(json.dumps(monitor.get_ram_info(), indent=2, ensure_ascii=False))
    
    print("\n4. Disque C:")
    print(json.dumps(monitor.get_disk_info("C"), indent=2, ensure_ascii=False))
    
    print("\n5. Batterie:")
    print(json.dumps(monitor.get_battery_info(), indent=2, ensure_ascii=False))
    
    print("\n6. Réseau:")
    print(json.dumps(monitor.get_network_info(), indent=2, ensure_ascii=False))
    
    print("\7. Carte graphique:")
    print(json.dumps(monitor.get_gpu_info(), indent=2, ensure_ascii=False))
    
    print("\n8. Statut global:")
    print(json.dumps(monitor.get_overall_status(), indent=2, ensure_ascii=False))
    
    print("\n--- Format voix ---")
    print(format_status_for_voice(monitor.get_overall_status()))
        try:
            cpu = self.get_cpu_info()
            ram = self.get_ram_info()
            disks = self.get_disk_info()
            gpu = self.get_gpu_info()
            battery = self.get_battery_info()
            network = self.get_network_info()
            system = self.get_system_info()
            
            problems = []
            severity_level = "normal"
            
            # 1. Surchauffe CPU
            cpu_temp = cpu.get("temperature", "Non disponible")
            if cpu_temp and cpu_temp not in ["Non disponible", "Erreur"]:
                try:
                    temp_val = float(cpu_temp)
                    if temp_val > 80:
                        problems.append({
                            "type": "surchauffe_cpu",
                            "description": f"CPU à {temp_val}°C",
                            "severity": "elevee",
                            "consequences": "Ralentissement, instabilité, dommage matériel possible",
                            "solution": "Nettoyer les ventilateurs, améliorer le refroidissement"
                        })
                        severity_level = "elevee"
                except:
                    pass
            
            # 2. Surchauffe GPU
            if gpu.get("gpus"):
                for gpu_item in gpu.get("gpus", []):
                    temp = gpu_item.get("temperature", "Non disponible")
                    if temp and temp not in ["Non disponible", "Erreur"]:
                        try:
                            temp_val = float(str(temp).replace("°C", "").strip())
                            if temp_val > 80:
                                gpu_name = gpu_item.get("name", "GPU")
                                problems.append({
                                    "type": "surchauffe_gpu",
                                    "description": f"{gpu_name} à {temp_val}°C",
                                    "severity": "moyenne",
                                    "consequences": "Throttling graphique, usure accélérée",
                                    "solution": "Vérifier le refroidissement GPU, nettoyer les dépoussiérages"
                                })
                                severity_level = max(severity_level, "moyenne")
                        except:
                            pass
            
            # 3. Saturation RAM
            ram_percent = ram.get("percent_used", 0)
            if ram_percent > 85:
                problems.append({
                    "type": "saturation_ram",
                    "description": f"RAM à {ram_percent}%",
                    "severity": "moyenne",
                    "consequences": "Ralentissement des apps, utilisation disque comme RAM virtuelle",
                    "solution": "Fermer applications inutiles, ajouter de la mémoire"
                })
                severity_level = max(severity_level, "moyenne")
            
            # 4. Disque presque plein
            if disks.get("disks"):
                for disk in disks.get("disks", []):
                    if disk.get("percent_used", 0) > 90:
                        problems.append({
                            "type": "disque_presque_plein",
                            "description": f"Disque {disk.get('device', 'C:')} à {disk.get('percent_used', 0)}%",
                            "severity": "elevee",
                            "consequences": "Performances drastiques, impossible d'enregistrer",
                            "solution": "Libérer de l'espace, déplacer des fichiers vers un autre disque"
                        })
                        severity_level = max(severity_level, "elevee")
            
            # 5. Batterie faible
            if battery.get("low_battery_warning"):
                problems.append({
                    "type": "batterie_faible",
                    "description": battery["low_battery_warning"],
                    "severity": "faible",
                    "consequences": "Arrêt imminent si plus d'autonomie",
                    "solution": "Connecter l'alimentation"
                })
            
            # 6. Problème réseau détecté
            if network.get("type_connexion") == "Non détecté":
                problems.append({
                    "type": "probleme_reseau",
                    "description": "Connexion réseau non détectée",
                    "severity": "moyenne",
                    "consequences": "Accès Internet interrompu",
                    "solution": "Vérifier la connexion réseau, redémarrer le routeur"
                })
            
            return {
                "overall_severity": severity_level,
                "problems_found": problems if problems else [],
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "summary": self._generate_summary(problems)
            }
        except Exception as e:
            return {"error": str(e), "overall_severity": "inconnu", "problems_found": []}
    
    def _generate_summary(self, problems):
        """Génère un résumé textuel des problèmes."""
        if not problems:
            return "✅ Tout va bien - Aucun problème détecté"
        
        critical = [p for p in problems if p.get("severity") == "elevee"]
        warning = [p for p in problems if p.get("severity") == "moyenne"]
        info = [p for p in problems if p.get("severity") == "faible"]
        
        summary_parts = []
        if critical:
            summary_parts.append(f"🔴 {len(critical)} problème critique")
        if warning:
            summary_parts.append(f"🟡 {len(warning)} problème d'attention")
        if info:
            summary_parts.append(f"🟢 {len(info)} information")
        
 return " | ".join(summary_parts) if summary_parts else "Problèmes détectés"
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        
        try:
            info = {
                "connected": True,
                "ip_address": "Non détecté",
                "type_connexion": "Inconnu",
                "upload_speed_kbps": "Non disponible",
                "download_speed_kbps": "Non disponible",
                "latency_ms": "Non disponible",
                "packet_loss_percent": "Non disponible",
                "interfaces": []
            }
            
            # Adresses IP des interfaces
            addrs = psutil.net_if_addrs()
            for interface_name, addr_list in addrs.items():
                for addr in addr_list:
                    if addr.family.name == 'AF_INET':  # IPv4
                        info["ip_address"] = addr.address
                        # Déterminer le type de connexion
                        if "Wi-Fi" in interface_name or "Wireless" in interface_name:
                            info["type_connexion"] = "Wi-Fi"
                        elif "Ethernet" in interface_name or "eth" in interface_name.lower():
                            info["type_connexion"] = "Câble Ethernet"
                        break
            
            # Stats E/S réseau
            io_counters = psutil.net_io_counters()
            if io_counters:
                # Les vitesses instantanées ne sont pas directement disponibles
                # on fournit les totaux mais en Ko pour être lisible
                info["total_sent_bytes"] = io_counters.bytes_sent
                info["total_recv_bytes"] = io_counters.bytes_recv
            
            # Processus consommateurs de réseau
            try:
                net_processes = []
                for proc in psutil.process_iter(['pid', 'name', 'net_io_counters']):
                    try:
                        nets = proc.info['net_io_counters']
                        if nets and (nets.bytes_sent > 1024 * 1024 or nets.bytes_recv > 1024 * 1024):
                            net_processes.append({
                                "name": proc.info['name'] or "inconnu",
                                "sent_mb": round(nets.bytes_sent / (1024 * 1024), 1),
                                "recv_mb": round(nets.bytes_recv / (1024 * 1024), 1),
                                "pid": proc.info['pid']
                            })
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
                net_processes.sort(key=lambda x: x['sent_mb'] + x['recv_mb'], reverse=True)
                info["top_consumers"] = net_processes[:5]
            except:
                info["top_consumers"] = []
            
            return info
        except Exception as e:
            return {"error": str(e)}
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        
        try:
            # Vérifier si batterie présente (None sur un bureau)
            battery = psutil.sensors_battery()
            
            if battery is None:
                return {
                    "present": False,
                    "type": "ordinateur_de_bureau",
                    "message": "Aucune batterie détectée (ordinateur fixe)"
                }
            
            percent = battery.percent
            plugged = battery.power_plugged
            
            # Estimer temps restant
            secs_left = battery.secsleft
            if secs_left > 0:
                hours = secs_left // 3600
                minutes = (secs_left % 3600) // 60
                time_remaining = f"{hours} heure{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes > 1 else ''}"
            elif secs_left == 0:
                time_remaining = "Connecté au secteur (batterie pleine)"
            else:
                time_remaining = "Non disponible"
            
            # Santé de la batterie (débit cycles, capacité)
            # Note: sur Windows, psutil.sensors_battery() ne fournit que le pourcentage
            # et l'état secteur. Les infos détaillées nécessitent WMI.
            battery_info = {
                "present": True,
                "percent": percent,
                "plugged": plugged,
                "charging": not plugged and percent < 100,
                "discharging": plugged is False and percent < 100,
                "full": percent >= 100,
                "time_remaining": time_remaining,
                "is_desktop": False
            }
            
            # Détection décharge anormale
            if not plugged and percent < 15:
                battery_info["low_battery_warning"] = "⚠️ Batterie faible - Connectez l'alimentation"
            else:
                battery_info["low_battery_warning"] = None
            
            return battery_info
        except Exception as e:
            return {"error": str(e)}
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        
        try:
            # Obtenir la partition demandée
            partition = psutil.disk_partitions(all=False)
            
            # Chercher la lettre demandée
            target_partition = None
            for p in partition:
                if p.device.upper().startswith(drive.upper()) or p.mountpoint.upper().startswith(f"{drive.upper()}:\\"):
                    target_partition = p
                    break
            
            if not target_partition:
                # Utiliser C: par défaut
                target_partition = psutil.disk_partitions(all=False)[0] if psutil.disk_partitions(all=False) else None
            
            if not target_partition:
                return {"error": "Aucun disque détecté"}
            
            usage = psutil.disk_usage(target_partition.mountpoint)
            
            # Obtenir les stats d'E/S
            io_counters = psutil.disk_io_counters()
            read_bytes = 0
            write_bytes = 0
            if io_counters:
                # Trouver le bon compteur pour cette partition
                for part in psutil.disk_partitions(all=False):
                    if part.device == target_partition.device:
                        # On utilise les stats globales
                        read_bytes = io_counters.read_bytes
                        write_bytes = io_counters.write_bytes
                        break
            
            risk_full = "⚠️ Disque presque plein - Supprimez des fichiers" if usage.percent > 90 else None
            
            return {
                "device": target_partition.device,
                "mountpoint": target_partition.mountpoint,
                "file_system": target_partition.fstype,
                "total_gb": round(usage.total / (1024 * 1024 * 1024), 2),
                "used_gb": round(usage.used / (1024 * 1024 * 1024), 2),
                "free_gb": round(usage.free / (1024 * 1024 * 1024), 2),
                "percent_used": usage.percent,
                "risk_near_full": usage.percent > 90,
                "read_bytes_total": read_bytes,
                "write_bytes_total": write_bytes,
                "status": "Critique" if usage.percent > 95 else ("Alerte" if usage.percent > 90 else "Normal")
            }
        except Exception as e:
            return {"error": str(e)}
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        
        try:
            mem = psutil.virtual_memory()
            
            # Processus consommant le plus de mémoire
            top_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    mem_info = proc.info['memory_info']
                    if mem_info:
                        top_processes.append({
                            "name": proc.info['name'] or "inconnu",
                            "memory_mb": round(mem_info.rss / (1024 * 1024), 1),
                            "pid": proc.info['pid']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            top_processes.sort(key=lambda x: x['memory_mb'], reverse=True)
            
            risk_threshold = 85
            saturation_warning = "⚠️ Risque de saturation de mémoire" if mem.percent > risk_threshold else None
            
            return {
                "total_gb": round(mem.total / (1024 * 1024 * 1024), 2),
                "available_gb": round(mem.available / (1024 * 1024 * 1024), 2),
                "used_gb": round(mem.used / (1024 * 1024 * 1024), 2),
                "percent_used": mem.percent,
                "free_gb": round(mem.free / (1024 * 1024 * 1024), 2),
                "top_consumers": top_processes[:5],
                "risk_saturation": mem.percent > risk_threshold,
                "saturation_warning": saturation_warning
            }
        except Exception as e:
            return {"error": str(e)}
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible", "gpus": []}
        
        try:
            gpus = []
            
            # Essayer d'utiliser GPUtil d'abord
            try:
                import GPUtil
                detected_gpus = GPUtil.getGPUs()
                for gpu in detected_gpus:
                    gpus.append({
                        "name": gpu.name,
                        "memory_total_mb": gpu.memoryTotal,
                        "memory_used_mb": gpu.memoryUsed,
                        "memory_free_mb": gpu.memoryFree,
                        "memory_percent": round(gpu.memoryUsed * 100 / gpu.memoryTotal, 1) if gpu.memoryTotal > 0 else 0,
                        "usage_percent": gpu.utilizationMemory * 100 if gpu.utilizationMemory else 0,
                        "temperature": gpu.temperature if gpu.temperature else "Non disponible",
                        "driver_version": gpu.driverVersion
                    })
            except ImportError:
                # Fallback avec psutil et WMI de base
                try:
                    import wmi
                    c = wmi.WMI()
                    for gpu in c.Win32_VideoController():
                        name = gpu.Name or "Carte graphique"
                        memory_mb = 0
                        if gpu.AdapterRAM:
                            memory_mb = gpu.AdapterRAM / (1024 * 1024)
                        
                        gpus.append({
                            "name": name,
                            "memory_total_mb": memory_mb,
                            "memory_used_mb": "Non disponible",
                            "memory_free_mb": "Non disponible",
                            "usage_percent": "Non disponible",
                            "temperature": "Non disponible via WMI",
                            "driver_version": gpu.DriverVersion or "Non disponible",
                            "is_integrated": getattr(gpu, 'IntegratedGraphics', False)
                        })
                except ImportError:
                    gpus = [{"name": "Non détectée", "error": "Aucune méthode de détection GPU disponible"}]
                except Exception:
                    gpus = [{"name": "Erreur détection", "error": "Impossible de récupérer les infos GPU"}]
            
            # Déterminer si c'est intégré ou dédié
            has_dedicated = any(
                gpu.get("name", "").lower() not in ["intel hd graphics", "intel iris", "intel hd graphics 500", "amd radeon", "radeon"] 
                for gpu in gpus
            ) or len(gpus) > 0 and all(gpu.get("memory_total_mb", 0) > 0 for gpu in gpus)
            
            return {
                "gpus": gpus,
                "has_dedicated": has_dedicated,
                "integrated_only": not has_dedicated and len(gpus) > 0
            }
        except Exception as e:
            return {"error": str(e), "gpus": []}
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        
        try:
            cpu_data = {
                "name": psutil.cpu_info().processor or "Processeur inconnu",
                "cores_physical": psutil.cpu_count(logical=False) or 1,
                "cores_total": psutil.cpu_count(logical=True) or 1,
                "usage_percent": psutil.cpu_percent(interval=0.1),
                "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
                "max_frequency_mhz": psutil.cpu_freq().max if psutil.cpu_freq() else None
            }
            return cpu_data
        except Exception as e:
            return {"error": str(e)}
        if not HAS_PSUTIL:
            return {"error": "psutil non disponible"}
        
        try:
            import platform
            return {
                "os": platform.system() + " " + platform.release(),
                "architecture": platform.architecture()[0],
                "processor": platform.processor() or "Inconnu",
                "boot_time": datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S"),
                "uptime": self._calculate_uptime(psutil.boot_time())
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _calculate_uptime(self, boot_time):
        """Calcule le temps depuis le dernier démarrage."""
        try:
            uptime = time.time() - boot_time
            days = int(uptime // 86400)
            hours = int((uptime % 86400) // 3600)
            minutes = int((uptime % 3600) // 60)
            if days > 0:
                return f"{days} jours, {hours} heures, {minutes} minutes"
            elif hours > 0:
                return f"{hours} heures, {minutes} minutes"
            else:
                return f"{minutes} minutes"
        except:
            return "Inconnu"
    Classe principale de surveillance du système NIANG IA.
    Fournit des méthodes pour collecter et analyser les données matérielles en temps réel.
    """
    
    def __init__(self):
        self.last_update = time.time()
        self.update_interval = 2.0
    from voice_activation import load_settings
except ImportError:
    pass

try:
    from ui import set_background_alpha, show_notification
except ImportError:
    pass
# Auteur : NIANG IA Project
# Surveillance matérielle en temps réel sous Windows 11

import os
import sys
import time
import json
import warnings
from datetime import datetime

# Import des bibliothèques disponibles
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Configuration du logging silencieux des avertissements
warnings.filterwarnings("ignore")