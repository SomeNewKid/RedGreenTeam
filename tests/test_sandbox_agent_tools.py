"""Tests for Sandbox Agent tools."""

from __future__ import annotations

import base64
import json

import pytest

from sandbox_agent.tools import (
    create_solution_skeleton,
    generate_image,
    generate_image_artifact,
    get_active_items,
    get_answer_format,
    get_html_element_name,
    get_test_assessment,
    jina_read_url,
    microsoft_code_sample_search,
    microsoft_docs_fetch,
    microsoft_docs_search,
    read_shared_file,
    request_code_update,
    request_solution_stub,
    request_test_creation,
    run_python_script,
    run_red_green_loop,
    save_answer,
    save_image,
    save_shared_file,
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


def test_create_solution_skeleton_writes_shared_solution_file(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify the coordinator creates the initial shared solution.py skeleton."""
    shared_path = tmp_path / "shared"
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))

    result = create_solution_skeleton("Implement slugify_title(title: str) -> str.")

    solution_path = shared_path / "solution.py"
    assert result == {
        "success": True,
        "message": "Created solution.py",
    }
    assert solution_path.exists()
    solution_text = solution_path.read_text(encoding="utf-8")
    assert "Implement slugify_title(title: str) -> str." in solution_text
    assert "def slugify_title(title: str) -> str:" in solution_text
    assert "raise NotImplementedError" in solution_text


def test_save_and_read_shared_file_round_trips_text(tmp_path, monkeypatch) -> None:
    """Verify shared text artifacts are saved under the shared directory."""
    shared_path = tmp_path / "shared"
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))

    result = save_shared_file("tests.py", "assert True\n")

    assert result == {
        "success": True,
        "message": "Created tests.py",
    }
    assert read_shared_file("tests.py") == "assert True\n"


def test_save_shared_file_rejects_parent_escape(tmp_path, monkeypatch) -> None:
    """Verify shared text artifacts cannot be saved outside the shared directory."""
    shared_path = tmp_path / "shared"
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))

    result = save_shared_file("../solution.py", "bad = True\n")

    assert result == {
        "success": False,
        "message": "Failed to save `../solution.py",
    }
    assert not (tmp_path / "solution.py").exists()


def test_get_test_assessment_calls_tester_agent(monkeypatch) -> None:
    """Verify test assessment uses the tester_agent run-tests action."""
    calls = []

    def fake_read_card(base_url: str) -> dict[str, object]:
        calls.append(("card", base_url))
        return {"url": f"{base_url}/a2a"}

    def fake_send_task(endpoint_url: str, text: str, **kwargs: object) -> str:
        calls.append(("task", endpoint_url, text, kwargs))
        return '{"agent": "tester_agent", "passed": false}'

    monkeypatch.setenv("TESTER_AGENT_URL", "http://tester-agent:8080")
    monkeypatch.setattr("sandbox_agent.tools.read_agent_card", fake_read_card)
    monkeypatch.setattr(
        "sandbox_agent.tools.send_text_task_and_wait_for_text_artifact",
        fake_send_task,
    )

    result = get_test_assessment("Implement slugify_title(title: str) -> str.")

    assert result == '{"agent": "tester_agent", "passed": false}'
    assert calls == [
        ("card", "http://tester-agent:8080"),
        (
            "task",
            "http://tester-agent:8080/a2a",
            (
                '{"action": "run_tests", "requirement": '
                '"Implement slugify_title(title: str) -> str."}'
            ),
            {
                "request_id": "tester-agent-task-request",
                "timeout_seconds": 300,
                "poll_interval_seconds": 1.0,
            },
        ),
    ]


def test_request_code_update_calls_coder_agent(monkeypatch) -> None:
    """Verify code updates use the coder_agent update action."""
    calls = []

    def fake_read_card(base_url: str) -> dict[str, object]:
        calls.append(("card", base_url))
        return {"url": f"{base_url}/a2a"}

    def fake_send_task(endpoint_url: str, text: str, **kwargs: object) -> str:
        calls.append(("task", endpoint_url, text, kwargs))
        return '{"agent": "coder_agent", "updated": true}'

    monkeypatch.setenv("CODER_AGENT_URL", "http://coder-agent:8080")
    monkeypatch.setattr("sandbox_agent.tools.read_agent_card", fake_read_card)
    monkeypatch.setattr(
        "sandbox_agent.tools.send_text_task_and_wait_for_text_artifact",
        fake_send_task,
    )

    result = request_code_update("Implement slugify_title(title: str) -> str.")

    assert result == '{"agent": "coder_agent", "updated": true}'
    assert calls == [
        ("card", "http://coder-agent:8080"),
        (
            "task",
            "http://coder-agent:8080/a2a",
            (
                '{"action": "update_solution", "requirement": '
                '"Implement slugify_title(title: str) -> str."}'
            ),
            {
                "request_id": "coder-agent-task-request",
                "timeout_seconds": 300,
                "poll_interval_seconds": 1.0,
            },
        ),
    ]


def test_request_solution_stub_calls_coder_agent(monkeypatch) -> None:
    """Verify stub creation uses the coder_agent create-stub action."""
    calls = []

    def fake_read_card(base_url: str) -> dict[str, object]:
        calls.append(("card", base_url))
        return {"url": f"{base_url}/a2a"}

    def fake_send_task(endpoint_url: str, text: str, **kwargs: object) -> str:
        calls.append(("task", endpoint_url, text, kwargs))
        return '{"agent": "coder_agent", "status": "stub_created"}'

    monkeypatch.setenv("CODER_AGENT_URL", "http://coder-agent:8080")
    monkeypatch.setattr("sandbox_agent.tools.read_agent_card", fake_read_card)
    monkeypatch.setattr(
        "sandbox_agent.tools.send_text_task_and_wait_for_text_artifact",
        fake_send_task,
    )

    result = request_solution_stub("Implement slugify_title(title: str) -> str.")

    assert result == '{"agent": "coder_agent", "status": "stub_created"}'
    assert calls == [
        ("card", "http://coder-agent:8080"),
        (
            "task",
            "http://coder-agent:8080/a2a",
            (
                '{"action": "create_stub", "requirement": '
                '"Implement slugify_title(title: str) -> str."}'
            ),
            {
                "request_id": "coder-agent-stub-request",
                "timeout_seconds": 300,
                "poll_interval_seconds": 1.0,
            },
        ),
    ]


def test_request_test_creation_calls_tester_agent(monkeypatch) -> None:
    """Verify test creation uses the tester_agent create-tests action."""
    calls = []

    def fake_read_card(base_url: str) -> dict[str, object]:
        calls.append(("card", base_url))
        return {"url": f"{base_url}/a2a"}

    def fake_send_task(endpoint_url: str, text: str, **kwargs: object) -> str:
        calls.append(("task", endpoint_url, text, kwargs))
        return '{"agent": "tester_agent", "status": "created"}'

    monkeypatch.setenv("TESTER_AGENT_URL", "http://tester-agent:8080")
    monkeypatch.setattr("sandbox_agent.tools.read_agent_card", fake_read_card)
    monkeypatch.setattr(
        "sandbox_agent.tools.send_text_task_and_wait_for_text_artifact",
        fake_send_task,
    )

    result = request_test_creation("Implement slugify_title(title: str) -> str.")

    assert result == '{"agent": "tester_agent", "status": "created"}'
    assert calls == [
        ("card", "http://tester-agent:8080"),
        (
            "task",
            "http://tester-agent:8080/a2a",
            (
                '{"action": "create_tests", "requirement": '
                '"Implement slugify_title(title: str) -> str."}'
            ),
            {
                "request_id": "tester-agent-create-tests-request",
                "timeout_seconds": 300,
                "poll_interval_seconds": 1.0,
            },
        ),
    ]


def test_run_red_green_loop_saves_final_answer(tmp_path, monkeypatch) -> None:
    """Verify the coordinator drives stub, tests, code, then red-green loops."""
    shared_path = tmp_path / "shared"
    answer_path = tmp_path / "answer.txt"
    test_results = [
        {"agent": "tester_agent", "status": "failed", "passed": False},
        {"agent": "tester_agent", "status": "passed", "passed": True},
    ]
    code_updates = []
    stub_requests = []
    test_creation_requests = []

    def fake_request_solution_stub(requirement: str) -> str:
        stub_requests.append(requirement)
        save_shared_file(
            "solution.py",
            "\n".join(
                [
                    '"""Solution."""',
                    "",
                    "",
                    "def slugify_title(title: str) -> str:",
                    "    raise NotImplementedError('not yet')",
                    "",
                ]
            ),
        )
        return json.dumps(
            {
                "agent": "coder_agent",
                "status": "stub_created",
                "updated": True,
            }
        )

    def fake_request_test_creation(requirement: str) -> str:
        test_creation_requests.append(requirement)
        save_shared_file(
            "tests.py",
            (
                "def run_tests() -> dict[str, object]:\n"
                "    return {\n"
                "        'passed': False,\n"
                "        'case_count': 1,\n"
                "        'failures': [{'title': 'Hello World'}],\n"
                "    }\n"
            ),
        )
        return json.dumps(
            {
                "agent": "tester_agent",
                "status": "created",
                "created": True,
            }
        )

    def fake_get_test_assessment(requirement: str) -> str:
        _ = requirement
        return json.dumps(test_results.pop(0))

    def fake_request_code_update(requirement: str) -> str:
        code_updates.append(requirement)
        save_shared_file(
            "solution.py",
            "\n".join(
                [
                    '"""Solution."""',
                    "",
                    "",
                    "def slugify_title(title: str) -> str:",
                    "    return 'hello-world'",
                    "",
                ]
            ),
        )
        return json.dumps(
            {
                "agent": "coder_agent",
                "status": "updated",
                "updated": True,
            }
        )

    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))
    monkeypatch.setattr("sandbox_agent.tools._ANSWER_FILE_PATH", answer_path)
    monkeypatch.setattr(
        "sandbox_agent.tools.request_solution_stub",
        fake_request_solution_stub,
    )
    monkeypatch.setattr(
        "sandbox_agent.tools.request_test_creation",
        fake_request_test_creation,
    )
    monkeypatch.setattr(
        "sandbox_agent.tools.get_test_assessment",
        fake_get_test_assessment,
    )
    monkeypatch.setattr(
        "sandbox_agent.tools.request_code_update",
        fake_request_code_update,
    )

    result = run_red_green_loop(
        "Implement slugify_title(title: str) -> str.",
        max_iterations=3,
    )

    assert result["passed"] is True
    assert stub_requests == ["Implement slugify_title(title: str) -> str."]
    assert test_creation_requests == ["Implement slugify_title(title: str) -> str."]
    assert code_updates == [
        "Implement slugify_title(title: str) -> str.",
        "Implement slugify_title(title: str) -> str.",
    ]
    attempts = result["attempts"]
    assert isinstance(attempts, list)
    assert len(attempts) == 2
    stub_creation = result["stub_creation"]
    tests_creation = result["tests_creation"]
    initial_code_update = result["initial_code_update"]
    assert isinstance(stub_creation, dict)
    assert isinstance(tests_creation, dict)
    assert isinstance(initial_code_update, dict)
    assert stub_creation["status"] == "stub_created"
    assert tests_creation["status"] == "created"
    assert initial_code_update["status"] == "updated"
    assert attempts[0]["code_update"] == {
        "agent": "coder_agent",
        "status": "updated",
        "updated": True,
    }
    assert attempts[1]["code_update"] is None
    answer_text = answer_path.read_text(encoding="utf-8")
    assert "RedGreenTeam TDD Result" in answer_text
    assert "Passed: True" in answer_text
    assert "return 'hello-world'" in answer_text
    assert "Final tests.py" in answer_text


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
    source_path = shared_path / "tester_agent" / "illustration.png"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"fake png bytes")
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(shared_path))
    monkeypatch.setattr("sandbox_agent.tools._SITE_DIRECTORY", site_path)

    result = save_shared_image_artifact(
        "illustration.png",
        "tester_agent/illustration.png",
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
