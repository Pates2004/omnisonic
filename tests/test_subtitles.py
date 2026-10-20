from __future__ import annotations

import codecs
import io
import unittest
from unittest.mock import Mock, patch

import numpy as np

from omnisonic.operations import OperationCancelled
from omnisonic.subtitles import (
    MAX_CUE_DURATION_MS,
    MAX_OUTPUT_FRAMES,
    MAX_SUBTITLE_BYTES,
    MAX_SUBTITLE_CUES,
    MAX_TIMELINE_MS,
    SubtitleCue,
    SubtitleError,
    read_subtitles,
    render_subtitles,
)
from tests.materials import scratch_directory


class SubtitleParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = scratch_directory("subtitle-parser-")

    def read(self, text, extension="srt", encoding="utf-8"):
        path = self.directory / ("input." + extension)
        path.write_bytes(text if isinstance(text, bytes) else text.encode(encoding))
        return read_subtitles(path)

    def assert_error(self, key, text, extension="srt", encoding="utf-8"):
        with self.assertRaises(SubtitleError) as raised:
            self.read(text, extension, encoding)
        self.assertEqual(raised.exception.message_key, "subtitle_" + key)
        return raised.exception

    def test_srt_multiline_both_time_separators_bom_and_nonsequential_identifiers(self):
        text = (
            "57\r\n00:00:01,025 --> 00:00:02,050\r\nFirst\r\nsecond line\r\n\r\n"
            "\r\n9\r\n00:00:02.050 --> 00:00:02.999\r\nThird\r\n"
        )
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-be"):
            with self.subTest(encoding=encoding):
                data = text.encode(encoding)
                if encoding == "utf-16-be":
                    data = codecs.BOM_UTF16_BE + data
                cues = self.read(data)
                self.assertEqual(
                    cues,
                    (
                        SubtitleCue(1, 1025, 2050, "First second line"),
                        SubtitleCue(2, 2050, 2999, "Third"),
                    ),
                )

    def test_vtt_header_metadata_settings_comments_style_and_regions_are_not_spoken(self):
        text = """WEBVTT - narration
Kind: captions
Language: en

NOTE a comment
not spoken

STYLE
::cue { color: lime }

REGION
id:fred
width:40%

opening identifier
00:01.125 --> 00:02.250 align:start position:10%
<v.first.loud Speaker><i>Hello</i> <lang en>world</lang>.

00:00:03.000 --> 00:00:04.000
Second.

NOTE trailing comment
"""
        self.assertEqual(
            self.read(text, "vtt", "utf-8-sig"),
            (
                SubtitleCue(1, 1125, 2250, "Hello world."),
                SubtitleCue(2, 3000, 4000, "Second."),
            ),
        )

    def test_markup_preserves_visible_text_voice_markers_and_ruby_base(self):
        payload = (
            r'{\an8}{\i1}<font color="#fff">A &amp; B</font>{\i0}<br/>'
            "<ruby>漢<rt>kan</rt>字<rt>ji</ruby> <00:01.500>"
            "<c.red>2 < 3</c> [laughter] &lt;b&gt;literal&lt;/b&gt;"
        )
        cue = self.read("1\n00:00:01,000 --> 00:00:03,000\n" + payload)[0]
        self.assertEqual(cue.text, "A & B 漢字 2 < 3 [laughter] <b>literal</b>")

    def test_webvtt_style_and_region_headers_allow_trailing_space_and_tab(self):
        for suffix in (" ", "\t", " \t"):
            with self.subTest(suffix=suffix):
                text = (
                    f"WEBVTT\n\nSTYLE{suffix}\n::cue {{ color: lime }}\n\n"
                    f"REGION{suffix}\nid:main\nwidth:40%\n\n"
                    "00:01.000 --> 00:02.000\nSpoken words"
                )
                self.assertEqual(
                    self.read(text, "vtt"), (SubtitleCue(1, 1000, 2000, "Spoken words"),)
                )

    def test_webvtt_metadata_keywords_can_also_be_cue_identifiers(self):
        for identifier in ("STYLE ", "REGION\t", "X-TIMESTAMP-MAP", "X-TIMESTAMP-MAP-scene"):
            with self.subTest(identifier=identifier):
                self.assertEqual(
                    self.read(
                        f"WEBVTT\n\n{identifier}\n00:01.000 --> 00:02.000\nSpoken words",
                        "vtt",
                    ),
                    (SubtitleCue(1, 1000, 2000, "Spoken words"),),
                )

    def test_webvtt_identifiers_allow_unicode_line_separator_characters(self):
        for separator in ("\u0085", "\u2028", "\u2029"):
            with self.subTest(separator=separator):
                self.assertEqual(
                    self.read(
                        f"WEBVTT\n\nscene{separator}one\n00:01.000 --> 00:02.000\nSpoken words",
                        "vtt",
                    ),
                    (SubtitleCue(1, 1000, 2000, "Spoken words"),),
                )

    def test_only_recognized_ass_and_html_markup_is_removed(self):
        text = r"{ordinary text} {\notastyle text} <custom>hello</custom> [cough]"
        cue = self.read("1\n00:00:01,000 --> 00:00:02,000\n" + text)[0]
        self.assertEqual(cue.text, text)
        styled = self.read(
            "1\n00:00:01,000 --> 00:00:02,000\n"
            r"{\pos(10,20)\an8\b1}Text{\b0}"
        )[0]
        self.assertEqual(styled.text, "Text")

    def test_malformed_ass_markup_is_literal_and_self_closing_ruby_does_not_hide_text(self):
        # A missing closing brace with many slashes must not trigger ambiguous
        # regex backtracking or cause the remainder of the narration to vanish.
        text = "{" + r"\i1" * 1000 + " ordinary text"
        cue = self.read("1\n00:00:01,000 --> 00:00:02,000\n" + text)[0]
        self.assertEqual(cue.text, text)
        cue = self.read("1\n00:00:01,000 --> 00:00:02,000\n<rt/>Visible")[0]
        self.assertEqual(cue.text, "Visible")

    def test_empty_markup_cues_fail_instead_of_silently_disappearing(self):
        for value in ("", "<i></i>", "<rt>annotation</rt>", r"{\an8}"):
            with self.subTest(value=value):
                error = self.assert_error("empty_cue", "1\n00:00:01,000 --> 00:00:02,000\n" + value)
                self.assertEqual(error.values, {"index": 1})

    def test_bad_syntax_and_missing_separators_fail_before_generation(self):
        for text in (
            "00:00:01,000 --> 00:00:02,000\nNo counter",
            "1\nnot a timestamp\nText",
            "1\n00:00:01,000 --> 00:00:02,000\nFirst\n2\n00:00:02,000 --> 00:00:03,000\nSecond",
            "1\n00:00:01,000 --> 00:00:02,000 align:start\nText",
        ):
            with self.subTest(text=text):
                self.assert_error("invalid_cue", text)

    def test_literal_arrows_in_srt_text_are_not_mistaken_for_timing_lines(self):
        for text in ("A --> B", "The diagram shows A --> B.", "A --> B --> C"):
            with self.subTest(text=text):
                self.assertEqual(
                    self.read("1\n00:00:01,000 --> 00:00:02,000\n" + text),
                    (SubtitleCue(1, 1000, 2000, text),),
                )
                self.assert_error(
                    "invalid_cue", "WEBVTT\n\n00:01.000 --> 00:02.000\n" + text, "vtt"
                )

    def test_srt_embedded_timings_still_reject_missing_cue_separators(self):
        for timing in (
            "00:00:02,000 --> 00:00:03,000",
            "00:60:02,000 --> invalid",
            "invalid --> 00:00:03,000",
            "invalid --> invalid",
        ):
            counters = ("2\n",) if timing == "invalid --> invalid" else ("2\n", "")
            for counter in counters:
                with self.subTest(timing=timing, counter=counter):
                    self.assert_error(
                        "invalid_cue",
                        "1\n00:00:00,000 --> 00:00:01,000\nFirst\n" + counter + timing + "\nSecond",
                    )

    def test_invalid_times_and_overlaps_identify_the_cue(self):
        for stamp in (
            "-1:00:00,000",
            "00:60:00,000",
            "00:00:60,000",
            "00:00:01,00",
            "0:00:01,000",
            "000000000000:00:01,000",
            "٠٠:00:01,000",
        ):
            with self.subTest(stamp=stamp):
                error = self.assert_error("invalid_timestamp", f"1\n{stamp} --> 00:00:02,000\nText")
                self.assertEqual(error.values["index"], 1)
        for end in ("00:00:01,000", "00:00:00,999"):
            self.assert_error("invalid_range", f"1\n00:00:01,000 --> {end}\nText")
        error = self.assert_error(
            "overlap",
            "1\n00:00:01,000 --> 00:00:03,000\nOne\n\n2\n00:00:02,000 --> 00:00:04,000\nTwo",
        )
        self.assertEqual(error.values, {"index": 2, "previous": 1})

    def test_webvtt_rejects_wrong_header_encoding_and_hls_timestamp_mapping(self):
        for text in ("", "NOTWEBVTT\n\n", "WEBVTT\n00:01.000 --> 00:02.000\nText"):
            self.assert_error("invalid_header", text, "vtt")
        self.assert_error("encoding_error", "WEBVTT\n\n", "vtt", "utf-16")
        for separator in ("\n", "\n\n"):
            for mapping in (
                "X-TIMESTAMP-MAP=LOCAL:00:00.000,MPEGTS:900000",
                " \tX-TIMESTAMP-MAP \t=LOCAL:00:00.000,MPEGTS:900000",
            ):
                with self.subTest(separator=separator, mapping=mapping):
                    self.assert_error(
                        "timestamp_map",
                        "WEBVTT" + separator + mapping + "\n\n00:00.000 --> 00:01.000\nText",
                        "vtt",
                    )

    def test_invalid_webvtt_cue_is_not_discarded_between_valid_ones(self):
        self.assert_error(
            "invalid_cue",
            "WEBVTT\n\n00:00.000 --> 00:01.000\nOne\n\ninvalid block\n\n"
            "00:02.000 --> 00:03.000\nThree",
            "vtt",
        )
        self.assert_error("invalid_timestamp", "WEBVTT\n\n00:01,000 --> 00:02.000\nText", "vtt")

    def test_missing_separator_does_not_hide_narration_inside_webvtt_metadata(self):
        for metadata in ("NOTE commentary", "STYLE\n::cue { color: red }", "REGION\nid:test"):
            with self.subTest(metadata=metadata):
                text = (
                    "WEBVTT\n\n00:00.000 --> 00:00.500\nFirst\n\n"
                    + metadata
                    + "\n00:01.000 --> 00:02.000\nLost words\n\n"
                    "00:02.000 --> 00:03.000\nThird"
                )
                error = self.assert_error("invalid_cue", text, "vtt")
                self.assertEqual(error.values["index"], 2)

    def test_file_and_timeline_limits(self):
        self.assert_error("unsupported_format", "anything", "ass")
        self.assert_error("empty", " \n\n")
        self.assert_error("encoding_error", b"\xff\xfe\xff")
        self.assert_error("encoding_error", "1\n00:00:01,000 --> 00:00:02,000\n\0")
        self.assert_error("too_large", b" " * (MAX_SUBTITLE_BYTES + 1))
        self.assert_error("cue_too_long", "1\n00:00:00,000 --> 00:02:00,001\nText")
        self.assert_error("timeline_limit", "1\n12:00:00,000 --> 12:00:01,000\nText")
        with patch("omnisonic.subtitles.MAX_SUBTITLE_CUES", 1):
            self.assert_error(
                "too_many",
                "1\n00:00:00,000 --> 00:00:01,000\nOne\n\n2\n00:00:01,000 --> 00:00:02,000\nTwo",
            )

    def test_cancellation_before_read_and_while_parsing_is_preserved(self):
        path = self.directory / "cancel.srt"
        path.write_text("1\n00:00:01,000 --> 00:00:02,000\nText", encoding="utf-8")
        for call in (1, 3):
            check = Mock(side_effect=[None] * (call - 1) + [OperationCancelled()])
            with self.assertRaises(OperationCancelled):
                read_subtitles(path, check)


class SubtitleRendererTests(unittest.TestCase):
    def test_exact_timeline_silences_short_audio_and_progress(self):
        cues = (
            SubtitleCue(1, 500, 1000, "One"),
            SubtitleCue(2, 1250, 2000, "Two"),
        )
        generate = Mock(side_effect=[np.full(300, 0.25), np.full(500, 0.5)])
        chunks = []
        progress = []
        render_subtitles(
            cues,
            1000,
            generate,
            lambda value: chunks.append(value.copy()),
            on_progress=lambda *value: progress.append(value),
        )
        audio = np.concatenate(chunks)
        expected = np.zeros(2000, dtype=np.float32)
        expected[500:800] = 0.25
        expected[1250:1750] = 0.5
        np.testing.assert_array_equal(audio, expected)
        self.assertEqual(generate.call_args_list[0].args, ("One", 0.5))
        self.assertEqual(generate.call_args_list[1].args, ("Two", 0.75))
        self.assertEqual(
            [(value[0], value[1]) for value in progress], [(0, 2), (1, 2), (1, 2), (2, 2)]
        )

    def test_boundary_rounding_does_not_accumulate_drift(self):
        cues = [SubtitleCue(index + 1, index * 7, (index + 1) * 7, "A") for index in range(100)]
        chunks = []
        render_subtitles(cues, 44_100, lambda *_: np.ones(300), chunks.append)
        self.assertEqual(sum(map(len, chunks)), 30_870)
        # Every cue begins at its rounded absolute timestamp, not previous length.
        audio = np.concatenate(chunks)
        for index in range(100):
            frame = (index * 7 * 44_100 + 500) // 1000
            self.assertEqual(audio[frame], 1)

    def test_all_cues_validated_before_first_synthesis_or_output(self):
        generate = Mock()
        write = Mock()
        invalid = (
            SubtitleCue(2, 500, 1500, "Overlap"),
            SubtitleCue(2, 1000, 1000, "Zero"),
            SubtitleCue(2, 1000, 1001, ""),
            SubtitleCue(2, 1000, 1001, "Tiny"),
        )
        for cue in invalid:
            with self.subTest(cue=cue):
                with self.assertRaises(SubtitleError):
                    render_subtitles([SubtitleCue(1, 0, 1000, "Valid"), cue], 1, generate, write)
                generate.assert_not_called()
                write.assert_not_called()

    def test_one_sample_overflow_is_explicit_and_speech_is_never_trimmed(self):
        write = Mock()
        with self.assertRaises(SubtitleError) as raised:
            render_subtitles(
                [SubtitleCue(1, 0, 1000, "One")], 1000, lambda *_: np.ones(1001), write
            )
        self.assertEqual(raised.exception.message_key, "subtitle_audio_overflow")
        self.assertEqual(raised.exception.values["actual_seconds"], 1.001)
        write.assert_not_called()

    def test_invalid_synthesis_audio_is_localized_without_writing(self):
        invalid = (
            np.zeros((1, 2)),
            np.array([]),
            np.array([np.nan]),
            np.array([np.inf]),
            np.array([True]),
            np.array([1 + 2j]),
            np.array(["text"]),
            np.array([1e300]),
            [[1], [1, 2]],
        )
        for value in invalid:
            with self.subTest(value=value):
                write = Mock()
                with self.assertRaises(SubtitleError) as raised:
                    render_subtitles(
                        [SubtitleCue(1, 0, 1000, "One")], 1000, Mock(return_value=value), write
                    )
                self.assertEqual(raised.exception.message_key, "subtitle_audio_invalid")
                write.assert_not_called()

    def test_large_silent_gap_is_streamed_in_bounded_blocks(self):
        sizes = []
        cue = SubtitleCue(1, MAX_TIMELINE_MS - 1000, MAX_TIMELINE_MS, "End")
        render_subtitles(
            [cue], 1000, lambda *_: np.ones(1000), lambda chunk: sizes.append(len(chunk))
        )
        self.assertEqual(sum(sizes), 43_200_000)
        self.assertLessEqual(max(sizes), 1000)

    def test_cancellation_interrupts_silent_stream_without_an_entire_movie_array(self):
        check = Mock()
        sizes = []

        def write(chunk):
            sizes.append(len(chunk))
            if len(sizes) == 3:
                check.side_effect = OperationCancelled()

        with self.assertRaises(OperationCancelled):
            render_subtitles(
                [SubtitleCue(1, 60_000, 61_000, "One")],
                1000,
                lambda *_: np.ones(100),
                write,
                check,
            )
        self.assertEqual(sizes, [1000, 1000, 1000])

    def test_sample_rate_limits_empty_inputs_and_callback_failures(self):
        cue = SubtitleCue(1, 0, 1000, "One")
        for rate in (0, -1, 1.5, True, np.bool_(False)):
            with self.subTest(rate=rate), self.assertRaises(SubtitleError) as raised:
                render_subtitles([cue], rate, Mock(), Mock())
            self.assertEqual(raised.exception.message_key, "subtitle_invalid_sample_rate")
        with self.assertRaises(SubtitleError) as raised:
            render_subtitles([], 1000, Mock(), Mock())
        self.assertEqual(raised.exception.message_key, "subtitle_empty")
        generate, write = Mock(), Mock()
        with self.assertRaises(SubtitleError) as raised:
            render_subtitles(
                [SubtitleCue(1, MAX_TIMELINE_MS - 1000, MAX_TIMELINE_MS, "End")],
                192_000,
                generate,
                write,
            )
        self.assertEqual(raised.exception.message_key, "subtitle_output_too_large")
        generate.assert_not_called()
        write.assert_not_called()
        for callback in (generate, write):
            callback.reset_mock(side_effect=True)
        generate.side_effect = RuntimeError("model failed")
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            render_subtitles([cue], 1000, generate, write)
        generate.side_effect = None
        generate.return_value = np.ones(100)
        write.side_effect = OSError("disk full")
        with self.assertRaisesRegex(OSError, "disk full"):
            render_subtitles([cue], 1000, generate, write)

    def test_limits_also_apply_to_direct_cues_and_iterables(self):
        cases = (
            ([SubtitleCue(1, 0, MAX_CUE_DURATION_MS + 1, "A")], "cue_too_long"),
            ([SubtitleCue(1, MAX_TIMELINE_MS, MAX_TIMELINE_MS + 1, "A")], "timeline_limit"),
            ([SubtitleCue(True, 0, 1000, "A")], "invalid_cue"),
            (["wrong"], "invalid_cue"),
            ((SubtitleCue(i + 1, i, i + 1, "A") for i in range(MAX_SUBTITLE_CUES + 1)), "too_many"),
        )
        for cues, suffix in cases:
            with self.subTest(suffix=suffix), self.assertRaises(SubtitleError) as raised:
                render_subtitles(cues, 1000, Mock(), Mock())
            self.assertEqual(raised.exception.message_key, "subtitle_" + suffix)
        self.assertGreater(MAX_OUTPUT_FRAMES, 2_000_000_000)

    def test_streamed_wave_is_a_valid_pcm16_file_with_exact_frame_count(self):
        import soundfile

        target = io.BytesIO()
        cues = [SubtitleCue(1, 25, 65, "One"), SubtitleCue(2, 100, 140, "Two")]
        with soundfile.SoundFile(
            target, "w", samplerate=24_000, channels=1, format="WAV", subtype="PCM_16"
        ) as writer:
            render_subtitles(
                cues, 24_000, lambda *_: np.full(800, 0.25, dtype=np.float32), writer.write
            )
        target.seek(0)
        audio, rate = soundfile.read(target)
        self.assertEqual(rate, 24_000)
        self.assertEqual(len(audio), 3360)
        np.testing.assert_array_equal(audio[:600], 0)
        np.testing.assert_allclose(audio[600:1400], 0.25, atol=1 / 32768)
        np.testing.assert_array_equal(audio[1560:2400], 0)


if __name__ == "__main__":
    unittest.main()
