package com.kaizumi.remote

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class ApiKeyStore(context: Context) {
    private val preferences = context.getSharedPreferences("niang_secure", Context.MODE_PRIVATE)
    private val alias = "niang_gemini_api_key"

    fun save(apiKey: String) {
        require(apiKey.isNotBlank()) { "La clé API ne peut pas être vide." }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(apiKey.toByteArray(Charsets.UTF_8))
        val value = ByteBuffer.allocate(cipher.iv.size + encrypted.size)
            .put(cipher.iv)
            .put(encrypted)
            .array()
        check(preferences.edit().putString("gemini_key", Base64.encodeToString(value, Base64.NO_WRAP)).commit()) {
            "Impossible d'enregistrer la clé Gemini sur cet appareil."
        }
    }

    fun load(): String? {
        val encoded = preferences.getString("gemini_key", null) ?: return null
        val value = Base64.decode(encoded, Base64.NO_WRAP)
        require(value.size > 12) { "La clé Gemini enregistrée est illisible. Saisissez-la à nouveau." }
        val buffer = ByteBuffer.wrap(value)
        val iv = ByteArray(12).also(buffer::get)
        val ciphertext = ByteArray(buffer.remaining()).also(buffer::get)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertext).toString(Charsets.UTF_8)
    }

    fun clear() {
        check(preferences.edit().remove("gemini_key").commit()) {
            "Impossible de supprimer la clé Gemini enregistrée."
        }
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build()
        )
        return generator.generateKey()
    }
}
