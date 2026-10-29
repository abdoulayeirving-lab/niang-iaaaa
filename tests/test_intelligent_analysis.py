import base64
import io
import sys
import tempfile
import unittest
import wave
import zipfile
from types import ModuleType
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from actions import document_qa, intelligent_analysis


class IntelligentAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_extracts_plain_text_csv_and_rtf(self):
        text = self.root / "notes.md"
        text.write_text("# Plan\nRéunion vendredi", encoding="utf-8")
        csv_file = self.root / "table.csv"
        csv_file.write_text("nom,montant\nAda,42", encoding="utf-8")
        rtf = self.root / "note.rtf"
        rtf.write_text(r"{\rtf1\b R\'e9sum\'e9\b0 le monde}", encoding="utf-8")

        self.assertIn("Réunion vendredi", intelligent_analysis.extract_source(str(text))["text"])
        self.assertEqual(
            intelligent_analysis.extract_source(str(csv_file))["text"],
            "nom | montant\nAda | 42",
        )
        self.assertIn("Résumé", intelligent_analysis.extract_source(str(rtf))["text"])

    def test_extracts_docx_and_rejects_corrupt_or_unsupported_files(self):
        docx = self.root / "brief.docx"
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr(
                "word/document.xml",
                "<w:document><w:p><w:r><w:t>Quarterly report</w:t></w:r></w:p></w:document>",
            )
        self.assertIn("Quarterly report", intelligent_analysis.extract_source(str(docx))["text"])

        corrupt = self.root / "broken.docx"
        corrupt.write_text("not a zip file", encoding="utf-8")
        with self.assertRaises(zipfile.BadZipFile):
            intelligent_analysis.extract_source(str(corrupt))

        unsupported = self.root / "program.exe"
        unsupported.write_bytes(b"binary")
        with self.assertRaisesRegex(ValueError, "Format non pris en charge"):
            intelligent_analysis.extract_source(str(unsupported))

    def test_rejects_oversized_file(self):
        path = self.root / "large.txt"
        path.write_text("some text", encoding="utf-8")
        with patch.object(intelligent_analysis, "MAX_FILE_BYTES", 4):
            with self.assertRaisesRegex(ValueError, "dépasse la limite"):
                intelligent_analysis.extract_source(str(path))

    def test_extracts_pdf_text_and_uses_ocr_for_scanned_pdf(self):
        pdf = self.root / "report.pdf"
        pdf.write_bytes(b"PDF fixture")
        with patch("actions.pdf_reader._extract_text", return_value="PDF text"):
            self.assertEqual(
                intelligent_analysis.extract_source(str(pdf))["text"], "PDF text"
            )
        with patch("actions.pdf_reader._extract_text", return_value=""), \
                patch.object(intelligent_analysis, "_ocr_pdf", return_value="OCR text") as ocr:
            self.assertEqual(
                intelligent_analysis.extract_source(str(pdf))["text"], "OCR text"
            )
        ocr.assert_called_once_with(pdf)

    def test_image_is_validated_and_sent_for_real_visual_analysis(self):
        image = self.root / "photo.png"
        image.write_bytes(b"image fixture")

        class FakeImage:
            width = 100
            height = 80

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def verify(self):
                return None

        pil = ModuleType("PIL")
        pil_image = ModuleType("PIL.Image")
        pil_image.open = Mock(return_value=FakeImage())
        pil.Image = pil_image
        with patch.dict(sys.modules, {"PIL": pil, "PIL.Image": pil_image}), \
                patch.object(intelligent_analysis, "_describe_image",
                             return_value="A readable street sign.") as describe:
            result = intelligent_analysis.extract_source(str(image))

        self.assertIn("street sign", result["text"])
        describe.assert_called_once_with(image)

    def test_analyzes_sources_with_explicit_untrusted_content_prompt(self):
        client = SimpleNamespace(
            interactions=SimpleNamespace(
                create=Mock(return_value=SimpleNamespace(output_text="Résumé vérifié."))
            ),
            close=Mock(),
        )
        with patch.object(intelligent_analysis, "_gemini_client", return_value=client):
            answer = intelligent_analysis.analyze_sources(
                [{"name": "notes.txt", "text": "Date : 12 juin"}],
                "Quelles sont les dates ?",
            )

        self.assertEqual(answer, "Résumé vérifié.")
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], intelligent_analysis.ANALYSIS_MODEL)
        prompt = call["input"]
        self.assertIn("n'exécute pas", prompt)
        self.assertIn("Date : 12 juin", prompt)
        self.assertIn("notes.txt", prompt)
        client.close.assert_called_once_with()

    def test_reports_truncated_analysis_context(self):
        client = SimpleNamespace(
            interactions=SimpleNamespace(
                create=Mock(return_value=SimpleNamespace(output_text="Résumé."))
            ),
            close=Mock(),
        )
        with patch.object(intelligent_analysis, "MAX_ANALYSIS_CHARS", 4), \
                patch.object(intelligent_analysis, "_gemini_client", return_value=client):
            answer = intelligent_analysis.analyze_sources([
                {"name": "long.txt", "text": "123456789"},
            ])
        self.assertIn("Limite d'analyse", answer)
        self.assertIn("long.txt", answer)

    def test_creates_real_wav_output_and_selects_voice(self):
        wav = io.BytesIO()
        with wave.open(wav, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24000)
            stream.writeframes(b"\x00\x00" * 24)
        interaction = SimpleNamespace(
            output_audio=SimpleNamespace(data=base64.b64encode(wav.getvalue()).decode("ascii"))
        )
        client = SimpleNamespace(interactions=SimpleNamespace(
            create=Mock(return_value=interaction),
        ), close=Mock())
        narration = "Bonjour. " + "mot " * 900
        with patch.object(intelligent_analysis, "_gemini_client", return_value=client):
            output = intelligent_analysis.generate_voiceover(
                narration, voice="Aoede", language="français", pace="lent", tone="calme",
            )
        self.addCleanup(lambda: output.unlink(missing_ok=True))

        with wave.open(str(output), "rb") as audio:
            self.assertEqual(audio.getnframes(), 24 * client.interactions.create.call_count)
            self.assertEqual(audio.getframerate(), 24000)
        self.assertEqual(client.interactions.create.call_count, 2)
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], "gemini-3.8-flash-tts")
        self.assertEqual(call["generation_config"]["speech_config"], [{"voice": "Aoede"}])
        client.close.assert_called_once_with()

    def test_splits_long_tts_text_without_dropping_sentence_punctuation(self):
        parts = intelligent_analysis.split_text("First sentence. " + "word " * 20, max_chars=16)
        self.assertGreater(len(parts), 1)
        self.assertTrue(parts[0].endswith("."))
        self.assertTrue(all(parts))
        with self.assertRaisesRegex(ValueError, "limite TTS"):
            with patch.object(intelligent_analysis, "MAX_AUDIO_CHARS", 3):
                intelligent_analysis.split_text("long")

    def test_media_transcription_deletes_temporary_gemini_upload(self):
        uploaded = SimpleNamespace(
            name="files/test-audio",
            uri="https://files.example/test-audio",
            mime_type="audio/mpeg",
            state=SimpleNamespace(name="ACTIVE"),
        )
        client = SimpleNamespace(
            files=SimpleNamespace(
                upload=Mock(return_value=uploaded),
                delete=Mock(),
            ),
            interactions=SimpleNamespace(
                create=Mock(return_value=SimpleNamespace(output_text="Transcription réelle."))
            ),
            close=Mock(),
        )
        audio = self.root / "sample.mp3"
        audio.write_bytes(b"audio")
        with patch.object(intelligent_analysis, "_gemini_client", return_value=client):
            text = intelligent_analysis._transcribe_media(audio)

        self.assertEqual(text, "Transcription réelle.")
        client.files.delete.assert_called_once_with(name="files/test-audio")
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], intelligent_analysis.ANALYSIS_MODEL)
        self.assertEqual(call["input"][1]["type"], "audio")
        self.assertEqual(call["input"][1]["uri"], uploaded.uri)
        client.close.assert_called_once_with()

    def test_video_transcription_uses_gemini_video_input(self):
        uploaded = SimpleNamespace(
            name="files/test-video",
            uri="https://files.example/test-video",
            mime_type="video/mp4",
            state=SimpleNamespace(name="ACTIVE"),
        )
        client = SimpleNamespace(
            files=SimpleNamespace(upload=Mock(return_value=uploaded), delete=Mock()),
            interactions=SimpleNamespace(
                create=Mock(return_value=SimpleNamespace(output_text="Transcription réelle."))
            ),
            close=Mock(),
        )
        video = self.root / "sample.mp4"
        video.write_bytes(b"video")

        with patch.object(intelligent_analysis, "_gemini_client", return_value=client):
            text = intelligent_analysis._transcribe_media(video)

        self.assertEqual(text, "Transcription réelle.")
        self.assertEqual(client.interactions.create.call_args.kwargs["input"][1]["type"], "video")
        client.files.delete.assert_called_once_with(name="files/test-video")
        client.close.assert_called_once_with()

    def test_image_analysis_keeps_gemini_client_open_until_request_finishes(self):
        image = self.root / "photo.png"
        image.write_bytes(b"image bytes")
        client = SimpleNamespace(
            interactions=SimpleNamespace(
                create=Mock(return_value=SimpleNamespace(
                    output_text="A verified image description."
                ))
            ),
            close=Mock(),
        )

        with patch.object(intelligent_analysis, "_gemini_client", return_value=client):
            result = intelligent_analysis._describe_image(image)

        self.assertEqual(result, "A verified image description.")
        call = client.interactions.create.call_args.kwargs
        self.assertEqual(call["model"], intelligent_analysis.ANALYSIS_MODEL)
        self.assertEqual(call["input"][1]["type"], "image")
        self.assertTrue(call["input"][1]["data"])
        client.close.assert_called_once_with()

    def test_extracts_url_title_and_rejects_empty_page_content(self):
        response = SimpleNamespace(
            headers={"Content-Type": "text/html; charset=utf-8"},
            text="<html><title>Public guide</title><body>Useful article text</body></html>",
        )
        with patch.object(document_qa, "_safe_get_url", return_value=response):
            source = intelligent_analysis.extract_source("https://example.com/guide")
        self.assertEqual(source["name"], "Public guide")
        self.assertIn("Useful article text", source["text"])

        response.text = "<html><title>Shell</title><body><script>dynamic()</script></body></html>"
        with patch.object(document_qa, "_safe_get_url", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "ne contient pas de texte"):
                intelligent_analysis.extract_source("https://example.com/app")


if __name__ == "__main__":
    unittest.main()
