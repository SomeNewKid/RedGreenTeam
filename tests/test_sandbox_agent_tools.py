"""Tests for Sandbox Agent tools."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from sandbox_agent.tools import (
    generate_image,
    generate_image_artifact,
    get_active_items,
    get_answer_format,
    get_html_element_name,
    get_parallel_bug_assessments,
    jina_read_url,
    microsoft_code_sample_search,
    microsoft_docs_fetch,
    microsoft_docs_search,
    run_python_script,
    save_answer,
    save_image,
    save_shared_image_artifact,
    validate_html5_element,
)


def test_validate_html5_element_accepts_element_name() -> None:
    """Verify HTML5 element validation accepts a plain element name."""
    result = validate_html5_element("main")

    assert result == {
        "element": "main",
        "is_html5": True,
    }


def test_validate_html5_element_normalizes_angle_brackets() -> None:
    """Verify HTML5 element validation accepts bracketed element names."""
    result = validate_html5_element("<IMG />")

    assert result == {
        "element": "img",
        "is_html5": True,
    }


def test_validate_html5_element_rejects_unknown_name() -> None:
    """Verify HTML5 element validation rejects unknown element names."""
    result = validate_html5_element("sparkle-box")

    assert result == {
        "element": "sparkle-box",
        "is_html5": False,
    }


def test_get_html_element_name_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify the HTML element tool calls the configured MCP sidecar."""
    called_urls = []

    def fake_call_mcp_html_element_tool(sidecar_url: str) -> str:
        called_urls.append(sidecar_url)
        return "<div>"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr(
        "sandbox_agent.tools._call_mcp_html_element_tool",
        fake_call_mcp_html_element_tool,
    )

    element_name = get_html_element_name()

    assert element_name == "<div>"
    assert called_urls == ["http://mcp-sidecar:8000/mcp"]


def test_get_html_element_name_requires_mcp_sidecar_url(monkeypatch) -> None:
    """Verify the HTML element tool requires MCP sidecar connection info."""
    monkeypatch.delenv("MCP_SIDECAR_URL", raising=False)

    with pytest.raises(RuntimeError, match="MCP_SIDECAR_URL"):
        get_html_element_name()


def test_get_active_items_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify active item lookups call the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, object]) -> str:
        calls.append((tool_name, arguments))
        return '[{"id": 2, "status": "active"}]'

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert get_active_items() == '[{"id": 2, "status": "active"}]'
    assert calls == [("get_active_items", {})]


def test_microsoft_docs_search_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Microsoft docs search calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "search result"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert microsoft_docs_search("MCP tool calling") == "search result"
    assert calls == [("microsoft_docs_search", {"query": "MCP tool calling"})]


def test_microsoft_docs_fetch_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Microsoft docs fetch calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "markdown"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert microsoft_docs_fetch("https://learn.microsoft.com/test") == "markdown"
    assert calls == [
        ("microsoft_docs_fetch", {"url": "https://learn.microsoft.com/test"})
    ]


def test_microsoft_code_sample_search_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Microsoft code sample search calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "code"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert microsoft_code_sample_search("agent framework", "python") == "code"
    assert calls == [
        (
            "microsoft_code_sample_search",
            {"query": "agent framework", "language": "python"},
        )
    ]


def test_jina_read_url_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Jina Reader calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, str]) -> str:
        calls.append((tool_name, arguments))
        return "markdown"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    assert jina_read_url("https://www.nibblon.com/movies/10") == "markdown"
    assert calls == [("jina_read_url", {"url": "https://www.nibblon.com/movies/10"})]


def test_run_python_script_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify Python execution calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, object]) -> str:
        calls.append((tool_name, arguments))
        return '{"exit_code": 0, "stdout": "42\\n"}'

    script = "def main(argv):\n    print(42)\n    return 0\n"
    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    result = run_python_script(script, args=["x"], timeout_seconds=5)

    assert result == '{"exit_code": 0, "stdout": "42\\n"}'
    assert calls == [
        (
            "run_python_script",
            {
                "script": script,
                "args": ["x"],
                "timeout_seconds": 5,
            },
        )
    ]


def test_generate_image_calls_mcp_sidecar(monkeypatch) -> None:
    """Verify image generation calls the sidecar wrapper tool."""
    calls = []

    def fake_call(tool_name: str, arguments: dict[str, object]) -> str:
        calls.append((tool_name, arguments))
        return '{"image_base64": "abc", "mime_type": "image/png"}'

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_sidecar_tool", fake_call)

    result = generate_image("A pencil sketch as a film still", "c2tldGNo")

    assert result == '{"image_base64": "abc", "mime_type": "image/png"}'
    assert calls == [
        (
            "generate_image",
            {
                "prompt": "A pencil sketch as a film still",
                "image_reference_base64": "c2tldGNo",
            },
        )
    ]


def test_generate_image_artifact_saves_image_without_returning_base64(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify image generation artifacts hide base64 from the model result."""
    site_path = tmp_path / "site"
    image_base64 = base64.b64encode(b"fake generated png bytes").decode("ascii")
    calls = []

    def fake_generate_image(
        prompt: str,
        image_reference_base64: str | None = None,
    ) -> str:
        calls.append((prompt, image_reference_base64))
        return (
            '{"image_base64": "'
            + image_base64
            + '", "mime_type": "image/png", "model": "gpt-image-1", '
            '"size": "1024x1024"}'
        )

    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)
    monkeypatch.setattr("sandbox_agent.tools.generate_image", fake_generate_image)

    result = generate_image_artifact(
        "A cinematic test image",
        "illustration.png",
        "cmVmZXJlbmNl",
    )

    assert calls == [("A cinematic test image", "cmVmZXJlbmNl")]
    assert result == {
        "success": True,
        "file_name": "illustration.png",
        "message": "Created illustration.png",
        "mime_type": "image/png",
        "model": "gpt-image-1",
        "size": "1024x1024",
        "byte_count": 24,
    }
    assert image_base64 not in str(result)
    assert (site_path / "illustration.png").read_bytes() == b"fake generated png bytes"


def test_generate_image_artifact_rejects_invalid_mcp_result(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify invalid MCP image responses do not create artifacts."""
    site_path = tmp_path / "site"

    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)
    monkeypatch.setattr(
        "sandbox_agent.tools.generate_image",
        lambda prompt, image_reference_base64=None: "{}",
    )

    result = generate_image_artifact("A cinematic test image", "illustration.png")

    assert result == {
        "success": False,
        "message": "Failed to create `illustration.png",
    }
    assert not (site_path / "illustration.png").exists()


def test_get_parallel_bug_assessments_starts_specialist_tasks(monkeypatch) -> None:
    """Verify bug assessment uses the parallel A2A helper for all specialists."""
    calls = []

    def fake_read_card(base_url: str) -> dict[str, object]:
        calls.append(("card", base_url))
        return {"url": f"{base_url}/a2a"}

    def fake_send_tasks(
        requests: tuple[Any, ...],
        **kwargs: object,
    ) -> tuple[object, ...]:
        calls.append(("tasks", requests, kwargs))
        return tuple(
            _FakeTextTaskArtifactResult(
                name=request.name,
                task_id=f"{request.name}-task",
                text=json.dumps(
                    {
                        "area": request.name,
                        "likelihood_percent": 70,
                        "reasons": ["Relevant symptom.", "Evidence is plausible."],
                    }
                ),
            )
            for request in requests
        )

    monkeypatch.setenv("FRONTEND_AGENT_URL", "http://frontend-agent:8080")
    monkeypatch.setenv("BACKEND_AGENT_URL", "http://backend-agent:8080")
    monkeypatch.setenv("DATABASE_AGENT_URL", "http://database-agent:8080")
    monkeypatch.setattr("sandbox_agent.tools.read_agent_card", fake_read_card)
    monkeypatch.setattr(
        "sandbox_agent.tools.send_text_tasks_and_wait_for_text_artifacts",
        fake_send_tasks,
    )

    result = get_parallel_bug_assessments("Profile updates disappear after refresh.")

    data = json.loads(result)
    assert data["bug_report"] == "Profile updates disappear after refresh."
    assert data["assessments"]["frontend"]["task_id"] == "frontend-task"
    assert data["assessments"]["backend"]["likelihood_percent"] == 70
    assert data["assessments"]["database"]["reasons"] == [
        "Relevant symptom.",
        "Evidence is plausible.",
    ]
    task_call = calls[3]
    assert task_call[0] == "tasks"
    requests = task_call[1]
    assert [request.name for request in requests] == [
        "frontend",
        "backend",
        "database",
    ]
    assert [request.endpoint_url for request in requests] == [
        "http://frontend-agent:8080/a2a",
        "http://backend-agent:8080/a2a",
        "http://database-agent:8080/a2a",
    ]


def test_get_answer_format_reads_mcp_sidecar_resource(monkeypatch) -> None:
    """Verify answer format reads the configured MCP sidecar resource."""
    calls = []

    def fake_call(sidecar_url: str, resource_uri: str) -> str:
        calls.append((sidecar_url, resource_uri))
        return "## Recommended Approach"

    monkeypatch.setenv("MCP_SIDECAR_URL", "http://mcp-sidecar:8000/mcp")
    monkeypatch.setattr("sandbox_agent.tools._call_mcp_resource", fake_call)

    assert get_answer_format() == "## Recommended Approach"
    assert calls == [
        (
            "http://mcp-sidecar:8000/mcp",
            "mcp-sidecar://instructions/answer-format.md",
        )
    ]


def test_save_answer_writes_answer_file(tmp_path, monkeypatch) -> None:
    """Verify answer text is saved to the sandbox output directory."""
    answer_path = tmp_path / "answer.txt"
    monkeypatch.setattr("sandbox_agent.tools._ANSWER_FILE_PATH", answer_path)

    result = save_answer("Answer text")

    assert result == {
        "success": True,
        "message": "Created answer.txt",
    }
    assert answer_path.read_text(encoding="utf-8") == "Answer text"


def test_save_image_writes_base64_image(tmp_path, monkeypatch) -> None:
    """Verify base64 image data is saved to the sandbox site directory."""
    site_path = tmp_path / "site"
    image_base64 = base64.b64encode(b"fake png bytes").decode("ascii")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)

    result = save_image("illustration.png", image_base64)

    assert result == {
        "success": True,
        "message": "Created illustration.png",
    }
    assert (site_path / "illustration.png").read_bytes() == b"fake png bytes"


def test_save_shared_image_artifact_copies_shared_file(tmp_path, monkeypatch) -> None:
    """Verify shared image artifacts can be copied into the web root."""
    site_path = tmp_path / "site"
    shared_path = tmp_path / "shared"
    source_path = shared_path / "frontend_agent" / "illustration.png"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"fake png bytes")
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)

    result = save_shared_image_artifact(
        "illustration.png",
        "frontend_agent/illustration.png",
    )

    assert result == {
        "success": True,
        "message": "Created illustration.png",
    }
    assert (site_path / "illustration.png").read_bytes() == b"fake png bytes"


def test_save_shared_image_artifact_rejects_parent_escape(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify shared artifact paths cannot escape the shared directory."""
    site_path = tmp_path / "site"
    shared_path = tmp_path / "shared"
    outside_path = tmp_path / "outside.png"
    outside_path.write_bytes(b"outside")
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)

    result = save_shared_image_artifact("illustration.png", "../outside.png")

    assert result == {
        "success": False,
        "message": "Failed to create `illustration.png",
    }
    assert not (site_path / "illustration.png").exists()


def test_save_image_rejects_invalid_base64(tmp_path, monkeypatch) -> None:
    """Verify invalid image data is reported as a failed create operation."""
    site_path = tmp_path / "site"
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)

    result = save_image("illustration.png", "not base64")

    assert result == {
        "success": False,
        "message": "Failed to create `illustration.png",
    }
    assert not (site_path / "illustration.png").exists()


def test_save_image_rejects_parent_directory_escape(tmp_path, monkeypatch) -> None:
    """Verify image artifacts cannot be saved outside the sandbox site."""
    site_path = tmp_path / "site"
    image_base64 = base64.b64encode(b"fake png bytes").decode("ascii")
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)

    result = save_image("../illustration.png", image_base64)

    assert result == {
        "success": False,
        "message": "Failed to create `../illustration.png",
    }
    assert not (tmp_path / "illustration.png").exists()


class _FakeTextTaskArtifactResult:
    def __init__(self, name: str, task_id: str, text: str) -> None:
        self.name = name
        self.task_id = task_id
        self.text = text
