import json

from sixstar.answer.extract import AnswerStreamExtractor
from sixstar.answer.llm import cost_usd, request_params
from sixstar.answer.prompt import answer_schema, system_blocks, user_message
from sixstar.common.config import Settings
from sixstar.common.text import clean_question, normalize_question, slugify
from sixstar.content.guide import parse_guide


def test_normalize_folds_spelling_variants():
    a = normalize_question("What time does GTA VI unlock??")
    b = normalize_question("what time does gta 6 unlock")
    c = normalize_question("  What TIME does Grand Theft Auto 6 unlock!  ")
    assert a == b == c == "what time does gta 6 unlock"


def test_clean_and_slug():
    assert clean_question("  hi\x00 there\n\n ", 300) == "hi there"
    assert clean_question("x" * 500, 300) == "x" * 300
    assert slugify("what time does gta 6 unlock") == "what-time-does-gta-6-unlock"
    assert len(slugify("word " * 50)) <= 72


def test_extractor_handles_chunks_and_escapes():
    payload = json.dumps({"answer": 'Line one\n"quoted" \\ café \U0001F600 end', "status": "answered"})
    ex = AnswerStreamExtractor()
    out = "".join(ex.feed(payload[i:i + 3]) for i in range(0, len(payload), 3))
    assert out == 'Line one\n"quoted" \\ café \U0001F600 end'
    assert ex.state == "done"


def test_extractor_when_answer_is_not_first():
    payload = '{"status":"answered","answer":"Hi there","claims":[]}'
    ex = AnswerStreamExtractor()
    assert "".join(ex.feed(c) for c in payload) == "Hi there"


GUIDE = """# Test guide

2026-11-14

## Launch essentials {#launch-essentials}

GTA 6 comes out November 19, 2026.

| a | b |
| --- | --- |

## Site name ideas {#site-name-ideas}

internal

## Rumors and conflicts {#rumors-and-conflicts}

- PC in 2027
"""


def test_guide_parser_ids_exclusion_and_version():
    g = parse_guide(GUIDE, ["site-name-ideas"])
    assert [s.id for s in g.sections] == ["launch-essentials", "rumors-and-conflicts"]
    assert g.sections[0].summary == "GTA 6 comes out November 19, 2026."
    assert "internal" not in g.prompt_text
    g2 = parse_guide(GUIDE.replace("November 19", "November 20"), ["site-name-ideas"])
    assert g.version != g2.version


def test_real_guide_parses():
    from sixstar.content.app import combined
    version, sections, text = combined()
    ids = [s.id for s in sections]
    assert "launch-essentials" in ids and "rumors-and-conflicts" in ids and "cheat-codes" in ids
    assert "site-name-ideas" not in ids
    assert version.startswith("g-")


def test_prompt_layout_is_cache_friendly():
    blocks = system_blocks("Guide", "<section>x</section>", "1h")
    assert "cache_control" not in blocks[0]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "Today's date" not in json.dumps(blocks)
    assert "Today's date" in user_message("q")
    assert "<question>q</question>" in user_message("q")


def test_schema_and_request_params():
    schema = answer_schema(["launch-essentials", "cheat-codes"])
    assert list(schema["properties"])[0] == "answer"
    assert schema["properties"]["sources"]["items"]["enum"] == ["launch-essentials", "cheat-codes"]
    s = Settings()
    params = request_params(s, system_blocks("G", "x", "1h"), "hi", schema)
    assert params["model"] == "claude-haiku-5-5"
    assert params["output_config"]["effort"] == "low"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert params["thinking"] == {"type": "disabled"}
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in params


def test_cost():
    from types import SimpleNamespace
    s = Settings()
    usage = SimpleNamespace(input_tokens=150, output_tokens=300, cache_read_input_tokens=6000,
                            cache_creation_input_tokens=0)
    # 150*0.10 + 6000*0.01 + 300*0.50 = 15 + 60 + 150 = 225 per million = $0.000225
    assert abs(cost_usd(usage, s) - 0.000225) < 1e-9
