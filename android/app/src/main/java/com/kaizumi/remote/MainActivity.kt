package com.kaizumi.remote

import android.Manifest
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.provider.AlarmClock
import android.provider.MediaStore
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.switchmaterial.SwitchMaterial
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.util.Locale

class MainActivity : AppCompatActivity() {
    companion object {
        private const val MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
    }

    private val keyStore by lazy { ApiKeyStore(this) }
    private val history = JSONArray()
    private val screenScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var selectedDocument: SelectedDocument? = null
    private var pendingAction: PendingAction? = null
    private var busy = false
    private var voiceDisclosureShown = false
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    private lateinit var statusView: TextView
    private lateinit var conversationView: TextView
    private lateinit var chatScroll: ScrollView
    private lateinit var promptInput: EditText
    private lateinit var webSearchSwitch: SwitchMaterial
    private lateinit var sendButton: Button
    private lateinit var voiceButton: Button
    private lateinit var documentButton: Button

    private val documentPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            val mime = contentResolver.getType(uri).orEmpty()
            val name = displayName(uri)
            if (mime !in setOf("application/pdf", "image/jpeg", "image/png", "text/plain")) {
                showError("Format non pris en charge. Choisissez un PDF, une image PNG/JPEG ou un fichier texte.")
            } else {
                selectedDocument = SelectedDocument(uri, mime, name)
                documentButton.text = name.take(18)
                statusView.text = getString(R.string.status_document_selected)
            }
        }
    }

    private val speechLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val recognized = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
                .orEmpty()
            if (result.resultCode == RESULT_OK && recognized.isNotBlank()) {
                promptInput.setText(recognized)
                sendMessage()
            } else if (result.resultCode == RESULT_OK) {
                statusView.text = getString(R.string.status_no_speech)
            }
        }

    private val microphonePermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) startSpeechRecognition()
            else showError("L’autorisation du microphone est nécessaire pour la saisie vocale.")
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_assistant)
        statusView = findViewById(R.id.statusView)
        conversationView = findViewById(R.id.conversationView)
        chatScroll = findViewById(R.id.chatScroll)
        promptInput = findViewById(R.id.promptInput)
        webSearchSwitch = findViewById(R.id.webSearchSwitch)
        sendButton = findViewById(R.id.sendButton)
        voiceButton = findViewById(R.id.voiceButton)
        documentButton = findViewById(R.id.documentButton)

        findViewById<Button>(R.id.keyButton).setOnClickListener { showApiKeyDialog() }
        documentButton.setOnClickListener { documentPicker.launch(arrayOf("*/*")) }
        findViewById<Button>(R.id.pcButton).setOnClickListener {
            startActivity(Intent(this, RemoteActivity::class.java))
        }
        sendButton.setOnClickListener { sendMessage() }
        voiceButton.setOnClickListener { requestVoiceInput() }
        promptInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendMessage()
                true
            } else {
                false
            }
        }

        tts = TextToSpeech(this) { result ->
            ttsReady = result == TextToSpeech.SUCCESS
            if (ttsReady) tts?.language = Locale.getDefault()
        }
        statusView.text = if (keyStore.load() == null) {
            "Ajoutez votre clé Gemini. Internet est requis."
        } else {
            "Prêt. Vos messages sont envoyés à Gemini lorsque vous les soumettez."
        }
    }

    private fun showApiKeyDialog() {
        val input = EditText(this).apply {
            hint = "Collez votre clé API Gemini"
            inputType = android.text.InputType.TYPE_CLASS_TEXT or
                android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
            maxLines = 1
        }
        val savedKey = keyStore.load()
        val dialog = AlertDialog.Builder(this)
            .setTitle("Clé API Gemini")
            .setMessage(
                "La clé est chiffrée avec Android Keystore sur cet appareil. " +
                    "Vos messages et documents sélectionnés sont envoyés à Google Gemini."
            )
            .setView(input)
            .setPositiveButton("Enregistrer", null)
            .setNeutralButton(if (savedKey == null) null else "Supprimer la clé", null)
            .setNegativeButton("Annuler", null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val value = input.text.toString().trim()
                if (value.isBlank()) {
                    input.error = "Saisissez une clé Gemini."
                    return@setOnClickListener
                }
                keyStore.save(value)
                statusView.text = getString(R.string.status_key_saved)
                dialog.dismiss()
            }
            if (savedKey != null) {
                dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                    keyStore.clear()
                    statusView.text = getString(R.string.status_key_removed)
                    dialog.dismiss()
                }
            }
        }
        dialog.show()
    }

    private fun requestVoiceInput() {
        if (!voiceDisclosureShown) {
            AlertDialog.Builder(this)
                .setTitle("Reconnaissance vocale")
                .setMessage(
                    "L’audio sera traité par le service de reconnaissance vocale configuré sur votre téléphone. " +
                        "Le texte reconnu sera envoyé à Gemini pour obtenir une réponse."
                )
                .setPositiveButton("Continuer") { _, _ ->
                    voiceDisclosureShown = true
                    requestMicrophonePermissionOrStart()
                }
                .setNegativeButton("Annuler", null)
                .show()
            return
        }
        requestMicrophonePermissionOrStart()
    }

    private fun requestMicrophonePermissionOrStart() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            startSpeechRecognition()
        } else {
            microphonePermission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun startSpeechRecognition() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
            .putExtra(RecognizerIntent.EXTRA_PROMPT, "Parlez à NIANG IA")
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        try {
            speechLauncher.launch(intent)
        } catch (_: ActivityNotFoundException) {
            showError("Aucun service de reconnaissance vocale n’est disponible sur ce téléphone.")
        }
    }

    private fun sendMessage() {
        if (busy) return
        val prompt = promptInput.text.toString().trim()
        val document = selectedDocument
        if (prompt.isBlank() && document == null) {
            promptInput.error = "Écrivez une question ou choisissez un document."
            return
        }
        val key = try {
            keyStore.load()
        } catch (error: Exception) {
            showError(error.message ?: "Impossible de lire la clé API. Saisissez-la à nouveau.")
            return
        }
        if (key.isNullOrBlank()) {
            showApiKeyDialog()
            return
        }
        val webSearch = webSearchSwitch.isChecked
        webSearchSwitch.isChecked = false
        promptInput.text.clear()
        appendMessage("Vous", prompt.ifBlank { "Analyse le document sélectionné." })
        setBusy(true, "NIANG IA réfléchit…")
        screenScope.launch {
            try {
                val attachment = document?.let { readAttachment(it) }
                val reply = GeminiClient.generate(
                    key,
                    history,
                    prompt,
                    webSearch,
                    attachment
                )
                if (reply.action != null) {
                    pendingAction = PendingAction(key, reply, attachment == null)
                    showActionConfirmation(reply.action)
                } else {
                    saveTurn(reply, attachment == null)
                    presentAnswer(reply.text)
                    setBusy(false, "Prêt")
                }
                selectedDocument = null
                documentButton.text = getString(R.string.document)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                setBusy(false, "Échec de la demande")
                showError(error.message ?: "La demande à Gemini a échoué.")
            }
        }
    }

    private suspend fun readAttachment(document: SelectedDocument): GeminiAttachment =
        withContext(Dispatchers.IO) {
            val bytes = contentResolver.openInputStream(document.uri)?.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                var total = 0
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= MAX_ATTACHMENT_BYTES) { "Le document dépasse la limite de 10 Mo." }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            } ?: error("Impossible de lire le document sélectionné.")
            GeminiAttachment(bytes, document.mimeType, document.name)
        }

    private fun showActionConfirmation(action: NativeAction) {
        val description = when (action.name) {
            "open_android_app" -> "Ouvrir ${action.arguments.optString("app")} sur ce téléphone"
            "set_alarm" -> {
                val hour = action.arguments.optInt("hour", -1)
                val minute = action.arguments.optInt("minute", -1)
                val label = action.arguments.optString("label")
                "Créer une alarme à %02d:%02d (%s)".format(hour, minute, label)
            }
            "create_reminder" -> {
                val title = action.arguments.optString("title").take(100)
                val dateTime = action.arguments.optString("date_time").take(32)
                "Ouvrir le calendrier pour créer « $title » le $dateTime"
            }
            "open_website" -> "Ouvrir ${action.arguments.optString("url")} dans le navigateur"
            else -> "Exécuter une action Android"
        }
        AlertDialog.Builder(this)
            .setTitle("Autoriser l’action Android ?")
            .setMessage("NIANG IA demande l’autorisation de :\n\n$description")
            .setPositiveButton("Autoriser") { _, _ -> executePendingAction(action, true) }
            .setNegativeButton("Refuser") { _, _ -> executePendingAction(action, false) }
            .setOnCancelListener { executePendingAction(action, false) }
            .show()
    }

    private fun executePendingAction(action: NativeAction, approved: Boolean) {
        val pending = pendingAction ?: return
        pendingAction = null
        screenScope.launch {
            try {
                val result = if (approved) performAndroidAction(action) else "Action refusée par l’utilisateur."
                val requestHistory = JSONArray(history.toString()).put(pending.reply.userContent)
                val answer = GeminiClient.continueAfterAction(
                    pending.apiKey,
                    requestHistory,
                    pending.reply.modelContent,
                    action,
                    result
                )
                saveTurn(pending.reply, pending.keepUserContent)
                appendHistory(
                    JSONObject()
                        .put("role", "model")
                        .put("parts", JSONArray().put(JSONObject().put("text", answer)))
                )
                presentAnswer(answer)
                setBusy(false, "Prêt")
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                setBusy(false, "L’action n’a pas abouti")
                showError(error.message ?: "L’action Android a échoué.")
            }
        }
    }

    private fun performAndroidAction(action: NativeAction): String {
        val intent = when (action.name) {
            "open_android_app" -> appIntent(action.arguments.optString("app"))
            "set_alarm" -> {
                val hour = action.arguments.optInt("hour", -1)
                val minute = action.arguments.optInt("minute", -1)
                require(hour in 0..23 && minute in 0..59) { "L’heure de l’alarme est invalide." }
                Intent(AlarmClock.ACTION_SET_ALARM)
                    .putExtra(AlarmClock.EXTRA_HOUR, hour)
                    .putExtra(AlarmClock.EXTRA_MINUTES, minute)
                    .putExtra(AlarmClock.EXTRA_MESSAGE, action.arguments.optString("label").take(60))
                    .putExtra(AlarmClock.EXTRA_SKIP_UI, false)
            }
            "create_reminder" -> {
                val title = action.arguments.optString("title").trim().take(100)
                require(title.isNotBlank()) { "Le titre du rappel est manquant." }
                val dateTime = try {
                    LocalDateTime.parse(action.arguments.optString("date_time"))
                } catch (_: DateTimeParseException) {
                    error("La date du rappel doit être fournie au format AAAA-MM-JJTHH:MM:SS.")
                }
                val begin = dateTime.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
                require(begin > System.currentTimeMillis()) { "La date du rappel doit être dans le futur." }
                Intent(Intent.ACTION_INSERT, android.provider.CalendarContract.Events.CONTENT_URI)
                    .putExtra(android.provider.CalendarContract.EXTRA_EVENT_BEGIN_TIME, begin)
                    .putExtra(android.provider.CalendarContract.EXTRA_EVENT_END_TIME, begin + 30 * 60 * 1000)
                    .putExtra(android.provider.CalendarContract.Events.TITLE, title)
            }
            "open_website" -> {
                val uri = Uri.parse(action.arguments.optString("url"))
                require(uri.scheme in setOf("http", "https") && !uri.host.isNullOrBlank() && uri.userInfo == null) {
                    "Seuls les liens Web publics http/https sont autorisés."
                }
                Intent(Intent.ACTION_VIEW, uri)
            }
            else -> error("Action Android inconnue.")
        }
        startActivity(intent)
        return "Android a accepté la demande d’ouverture, mais l’action finale n’est pas vérifiée. Ne prétends pas qu’elle est terminée."
    }

    private fun appIntent(app: String): Intent {
        val category = when (app) {
            "browser" -> Intent.CATEGORY_APP_BROWSER
            "camera" -> return Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            "calendar" -> Intent.CATEGORY_APP_CALENDAR
            "contacts" -> Intent.CATEGORY_APP_CONTACTS
            "email" -> Intent.CATEGORY_APP_EMAIL
            "settings" -> return Intent(Settings.ACTION_SETTINGS)
            "wifi_settings" -> return Intent(Settings.ACTION_WIFI_SETTINGS)
            "bluetooth_settings" -> return Intent(Settings.ACTION_BLUETOOTH_SETTINGS)
            else -> error("Cette application n’est pas dans la liste autorisée.")
        }
        return Intent(Intent.ACTION_MAIN).addCategory(category)
    }

    private fun saveTurn(reply: GeminiReply, keepUserContent: Boolean) {
        if (keepUserContent) {
            appendHistory(reply.userContent)
        } else {
            appendHistory(textOnlyUserContent(promptFrom(reply.userContent)))
        }
        appendHistory(reply.modelContent)
    }

    private fun appendHistory(content: JSONObject) {
        history.put(content)
        while (history.length() > 16) history.remove(0)
    }

    private fun textOnlyUserContent(text: String) = JSONObject()
        .put("role", "user")
        .put("parts", JSONArray().put(JSONObject().put("text", text)))

    private fun promptFrom(content: JSONObject): String {
        val parts = content.optJSONArray("parts") ?: return ""
        return (0 until parts.length())
            .mapNotNull { parts.optJSONObject(it)?.optString("text") }
            .joinToString("\n")
    }

    private fun presentAnswer(text: String) {
        appendMessage("NIANG IA", text)
        if (ttsReady) tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "niang-response")
    }

    private fun appendMessage(speaker: String, text: String) {
        conversationView.append("\n\n$speaker\n$text")
        chatScroll.post { chatScroll.fullScroll(ScrollView.FOCUS_DOWN) }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (index >= 0 && cursor.moveToFirst()) return cursor.getString(index)
        }
        return uri.lastPathSegment?.substringAfterLast('/') ?: "Document"
    }

    private fun setBusy(value: Boolean, status: String) {
        busy = value
        sendButton.isEnabled = !value
        voiceButton.isEnabled = !value
        statusView.text = status
    }

    private fun showError(message: String) {
        statusView.text = getString(R.string.status_error)
        AlertDialog.Builder(this)
            .setTitle("NIANG IA")
            .setMessage(message)
            .setPositiveButton("OK", null)
            .show()
    }

    override fun onDestroy() {
        screenScope.cancel()
        tts?.stop()
        tts?.shutdown()
        super.onDestroy()
    }

    private data class SelectedDocument(val uri: Uri, val mimeType: String, val name: String)
    private data class PendingAction(
        val apiKey: String,
        val reply: GeminiReply,
        val keepUserContent: Boolean
    )
}
