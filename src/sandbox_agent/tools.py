"""Tools used by the Sandbox Agent."""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from a2a_support.client import (
    TextTaskRequest,
    read_agent_card,
    read_agent_endpoint_url,
    send_text_tasks_and_wait_for_text_artifacts,
)

_OUTPUT_DIRECTORY = Path("/sandbox-output")
_SITE_DIRECTORY = _OUTPUT_DIRECTORY / "site"
_ANSWER_FILE_PATH = _OUTPUT_DIRECTORY / "answer.txt"
_SHARED_DIRECTORY_ENVIRONMENT_VARIABLE = "SANDBOX_SHARED_DIR"
_DEFAULT_SHARED_DIRECTORY = Path("/sandbox-shared")
_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_URL"
_MCP_ACTIVE_ITEMS_TOOL_NAME = "get_active_items"
_MCP_HTML_ELEMENT_TOOL_NAME = "get_html_element_name"
_MCP_MICROSOFT_DOCS_SEARCH_TOOL_NAME = "microsoft_docs_search"
_MCP_MICROSOFT_DOCS_FETCH_TOOL_NAME = "microsoft_docs_fetch"
_MCP_MICROSOFT_CODE_SAMPLE_SEARCH_TOOL_NAME = "microsoft_code_sample_search"
_MCP_JINA_READ_URL_TOOL_NAME = "jina_read_url"
_MCP_RUN_PYTHON_SCRIPT_TOOL_NAME = "run_python_script"
_MCP_GENERATE_IMAGE_TOOL_NAME = "generate_image"
_MCP_ANSWER_FORMAT_RESOURCE_URI = "mcp-sidecar://instructions/answer-format.md"
_FRONTEND_AGENT_URL_ENVIRONMENT_VARIABLE = "FRONTEND_AGENT_URL"
_DEFAULT_FRONTEND_AGENT_URL = "http://frontend-agent:8080"
_BACKEND_AGENT_URL_ENVIRONMENT_VARIABLE = "BACKEND_AGENT_URL"
_DEFAULT_BACKEND_AGENT_URL = "http://backend-agent:8080"
_DATABASE_AGENT_URL_ENVIRONMENT_VARIABLE = "DATABASE_AGENT_URL"
_DEFAULT_DATABASE_AGENT_URL = "http://database-agent:8080"
_HTML5_ELEMENTS = frozenset(
    {
        "a",
        "abbr",
        "address",
        "area",
        "article",
        "aside",
        "audio",
        "b",
        "base",
        "bdi",
        "bdo",
        "blockquote",
        "body",
        "br",
        "button",
        "canvas",
        "caption",
        "cite",
        "code",
        "col",
        "colgroup",
        "data",
        "datalist",
        "dd",
        "del",
        "details",
        "dfn",
        "dialog",
        "div",
        "dl",
        "dt",
        "em",
        "embed",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hgroup",
        "hr",
        "html",
        "i",
        "iframe",
        "img",
        "input",
        "ins",
        "kbd",
        "label",
        "legend",
        "li",
        "link",
        "main",
        "map",
        "mark",
        "menu",
        "meta",
        "meter",
        "nav",
        "noscript",
        "object",
        "ol",
        "optgroup",
        "option",
        "output",
        "p",
        "picture",
        "pre",
        "progress",
        "q",
        "rp",
        "rt",
        "ruby",
        "s",
        "samp",
        "script",
        "search",
        "section",
        "select",
        "slot",
        "small",
        "source",
        "span",
        "strong",
        "style",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "template",
        "textarea",
        "tfoot",
        "th",
        "thead",
        "time",
        "title",
        "tr",
        "track",
        "u",
        "ul",
        "var",
        "video",
        "wbr",
    }
)


def get_html_element_name() -> str:
    """Return the HTML element name provided by the MCP sidecar."""
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_html_element_tool(sidecar_url)


def get_active_items() -> str:
    """Return active item records provided by the MCP sidecar."""
    return _call_mcp_sidecar_tool(_MCP_ACTIVE_ITEMS_TOOL_NAME, {})


def microsoft_docs_search(query: str) -> str:
    """Search Microsoft Learn documentation through the MCP sidecar."""
    return _call_mcp_sidecar_tool(
        _MCP_MICROSOFT_DOCS_SEARCH_TOOL_NAME,
        {"query": query},
    )


def microsoft_docs_fetch(url: str) -> str:
    """Fetch a Microsoft Learn documentation page through the MCP sidecar."""
    return _call_mcp_sidecar_tool(_MCP_MICROSOFT_DOCS_FETCH_TOOL_NAME, {"url": url})


def microsoft_code_sample_search(query: str, language: str | None = None) -> str:
    """Search Microsoft Learn code samples through the MCP sidecar."""
    arguments = {"query": query}
    if language:
        arguments["language"] = language

    return _call_mcp_sidecar_tool(
        _MCP_MICROSOFT_CODE_SAMPLE_SEARCH_TOOL_NAME,
        arguments,
    )


def jina_read_url(url: str) -> str:
    """Read a fully-qualified URL through the Jina Reader sidecar."""
    return _call_mcp_sidecar_tool(_MCP_JINA_READ_URL_TOOL_NAME, {"url": url})


def run_python_script(
    script: str,
    args: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Run a small Python script through the MCP code-execution sidecar tool."""
    arguments: dict[str, object] = {"script": script}
    if args is not None:
        arguments["args"] = args
    if timeout_seconds is not None:
        arguments["timeout_seconds"] = timeout_seconds

    return _call_mcp_sidecar_tool(_MCP_RUN_PYTHON_SCRIPT_TOOL_NAME, arguments)


def generate_image(prompt: str, image_reference_base64: str | None = None) -> str:
    """Generate an image through the MCP sidecar."""
    arguments: dict[str, object] = {"prompt": prompt}
    if image_reference_base64 is not None:
        arguments["image_reference_base64"] = image_reference_base64

    return _call_mcp_sidecar_tool(_MCP_GENERATE_IMAGE_TOOL_NAME, arguments)


def generate_image_artifact(
    prompt: str,
    file_name: str,
    image_reference_base64: str | None = None,
) -> dict[str, object]:
    """Generate an image through MCP and save it into the sandbox web root."""
    try:
        result_text = generate_image(prompt, image_reference_base64)
        result = _read_generate_image_result(result_text)
        image_base64 = result["image_base64"]
        image_path = _resolve_site_path(file_name)
        image_bytes = _decode_base64_image(image_base64)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return _artifact_failure(file_name)

    if not image_path.exists():
        return _artifact_failure(file_name)

    return {
        "success": True,
        "file_name": file_name,
        "message": f"Created {file_name}",
        "mime_type": result.get("mime_type", "image/png"),
        "model": result.get("model", ""),
        "size": result.get("size", ""),
        "byte_count": len(image_bytes),
    }


def get_parallel_bug_assessments(bug_report: str) -> str:
    """Return frontend, backend, and database assessments from parallel A2A tasks."""
    requests = (
        _build_bug_assessment_task_request(
            "frontend",
            os.environ.get(
                _FRONTEND_AGENT_URL_ENVIRONMENT_VARIABLE,
                _DEFAULT_FRONTEND_AGENT_URL,
            ),
            bug_report,
        ),
        _build_bug_assessment_task_request(
            "backend",
            os.environ.get(
                _BACKEND_AGENT_URL_ENVIRONMENT_VARIABLE,
                _DEFAULT_BACKEND_AGENT_URL,
            ),
            bug_report,
        ),
        _build_bug_assessment_task_request(
            "database",
            os.environ.get(
                _DATABASE_AGENT_URL_ENVIRONMENT_VARIABLE,
                _DEFAULT_DATABASE_AGENT_URL,
            ),
            bug_report,
        ),
    )
    artifacts = send_text_tasks_and_wait_for_text_artifacts(
        requests,
        timeout_seconds=300,
        poll_interval_seconds=1.0,
    )

    assessments = {}
    for artifact in artifacts:
        assessment = json.loads(artifact.text)
        if not isinstance(assessment, dict):
            raise ValueError("Bug assessment artifact must be a JSON object.")

        assessments[artifact.name] = assessment | {"task_id": artifact.task_id}

    return json.dumps(
        {
            "bug_report": bug_report,
            "assessments": assessments,
        },
        sort_keys=True,
    )


def save_image(file_name: str, image_base64: str) -> dict[str, bool | str]:
    """Save a base64-encoded image into the sandbox web root."""
    try:
        image_path = _resolve_site_path(file_name)
        image_bytes = _decode_base64_image(image_base64)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
    except (OSError, ValueError):
        return _failure("create", file_name)

    if not image_path.exists():
        return _failure("create", file_name)

    return {
        "success": True,
        "message": f"Created {file_name}",
    }


def save_shared_image_artifact(
    file_name: str,
    artifact_path: str,
) -> dict[str, bool | str]:
    """Copy a shared image artifact into the sandbox web root."""
    try:
        source_path = _resolve_shared_path(artifact_path)
        image_path = _resolve_site_path(file_name)
        image_bytes = source_path.read_bytes()
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
    except OSError:
        return _failure("create", file_name)

    if not image_path.exists():
        return _failure("create", file_name)

    return {
        "success": True,
        "message": f"Created {file_name}",
    }


def get_answer_format() -> str:
    """Read the required answer format resource from the MCP sidecar."""
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_resource(sidecar_url, _MCP_ANSWER_FORMAT_RESOURCE_URI)


def validate_html5_element(element_name: str) -> dict[str, bool | str]:
    """Return whether a user-supplied name is a known HTML5 element."""
    normalized_name = _normalize_html_element_name(element_name)
    return {
        "element": normalized_name,
        "is_html5": normalized_name in _HTML5_ELEMENTS,
    }


def save_html_document(file_name: str, file_contents: str) -> dict[str, bool | str]:
    """Save an HTML document into the sandbox web root."""
    try:
        file_path = _resolve_site_path(file_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_contents, encoding="utf-8")
    except OSError:
        return _failure("create", file_name)

    if not file_path.exists():
        return _failure("create", file_name)

    return {
        "success": True,
        "message": f"Created {file_name}",
    }


def save_answer(answer: str) -> dict[str, bool | str]:
    """Save the generated answer into the sandbox output directory."""
    try:
        _ANSWER_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ANSWER_FILE_PATH.write_text(answer, encoding="utf-8")
    except OSError:
        return _failure("save", _ANSWER_FILE_PATH.name)

    if not _ANSWER_FILE_PATH.exists():
        return _failure("save", _ANSWER_FILE_PATH.name)

    return {
        "success": True,
        "message": f"Created {_ANSWER_FILE_PATH.name}",
    }


def _resolve_site_path(file_name: str) -> Path:
    return _resolve_child_path(_SITE_DIRECTORY, file_name)


def _build_bug_assessment_task_request(
    name: str,
    base_url: str,
    bug_report: str,
) -> TextTaskRequest:
    agent_card = read_agent_card(base_url)
    endpoint_url = read_agent_endpoint_url(agent_card)
    return TextTaskRequest(
        name=name,
        endpoint_url=endpoint_url,
        text=bug_report,
        request_id=f"{name}-agent-task-request",
    )


def _resolve_shared_path(artifact_path: str) -> Path:
    shared_directory = Path(
        os.environ.get(
            _SHARED_DIRECTORY_ENVIRONMENT_VARIABLE,
            str(_DEFAULT_SHARED_DIRECTORY),
        )
    )
    return _resolve_child_path(shared_directory, artifact_path)


def _call_mcp_html_element_tool(sidecar_url: str) -> str:
    return _call_mcp_tool(sidecar_url, _MCP_HTML_ELEMENT_TOOL_NAME, {})


def _call_mcp_sidecar_tool(tool_name: str, arguments: Mapping[str, object]) -> str:
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_tool(sidecar_url, tool_name, arguments)


def _call_mcp_resource(sidecar_url: str, resource_uri: str) -> str:
    import anyio

    return anyio.run(_call_mcp_resource_async, sidecar_url, resource_uri)


def _get_mcp_sidecar_url() -> str:
    sidecar_url = os.environ.get(_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE)
    if not sidecar_url:
        raise RuntimeError("MCP_SIDECAR_URL is not configured.")

    return sidecar_url


def _call_mcp_tool(
    sidecar_url: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    import anyio

    return anyio.run(_call_mcp_tool_async, sidecar_url, tool_name, arguments)


async def _call_mcp_tool_async(
    sidecar_url: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(sidecar_url) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, dict(arguments))

    return _read_mcp_tool_text_result(result)


async def _call_mcp_resource_async(sidecar_url: str, resource_uri: str) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from pydantic import AnyUrl

    async with streamablehttp_client(sidecar_url) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.read_resource(AnyUrl(resource_uri))

    return _read_mcp_resource_text_result(result)


def _read_mcp_tool_text_result(result: Any) -> str:
    structured_content = getattr(result, "structuredContent", None)
    if isinstance(structured_content, dict):
        value = structured_content.get("result")
        if isinstance(value, str):
            return value
        if value is not None:
            return json.dumps(value, indent=2)
        return json.dumps(structured_content, indent=2)

    content_blocks = getattr(result, "content", ())
    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text

    raise RuntimeError("MCP tool did not return a text result.")


def _read_mcp_resource_text_result(result: Any) -> str:
    contents = getattr(result, "contents", ())
    text_parts = [
        text
        for content in contents
        if isinstance((text := getattr(content, "text", None)), str)
    ]
    if text_parts:
        return "\n\n".join(text_parts)

    raise RuntimeError("MCP resource did not return text content.")


def _normalize_html_element_name(element_name: str) -> str:
    name = element_name.strip().lower()
    name = name.removeprefix("<")
    name = name.removeprefix("/")
    name = name.removesuffix(">")
    name = name.removesuffix("/")
    return name.strip()


def _decode_base64_image(image_base64: str) -> bytes:
    encoded_image = image_base64.strip()
    if encoded_image.lower().startswith("data:") and "," in encoded_image:
        _prefix, encoded_image = encoded_image.split(",", 1)
    if not encoded_image:
        raise ValueError("Image data must not be empty.")

    try:
        return base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Image data must be valid base64.") from error


def _read_generate_image_result(result_text: str) -> dict[str, str]:
    result = json.loads(result_text)
    if not isinstance(result, dict):
        raise ValueError("generate_image returned an unexpected result.")

    image_base64 = result.get("image_base64")
    if not isinstance(image_base64, str) or not image_base64:
        raise ValueError("generate_image returned no image_base64 value.")

    return {
        "image_base64": image_base64,
        "mime_type": _read_optional_string(result, "mime_type"),
        "model": _read_optional_string(result, "model"),
        "size": _read_optional_string(result, "size"),
    }


def _read_optional_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str):
        return value

    return ""


def _resolve_child_path(parent: Path, child_name: str) -> Path:
    child_path = parent / child_name
    resolved_parent = parent.resolve(strict=False)
    resolved_child = child_path.resolve(strict=False)
    if not _is_relative_to(resolved_child, resolved_parent):
        raise OSError(f"Refusing to write outside {resolved_parent}: {child_name}")

    return resolved_child


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False

    return True


def _failure(action: str, file_name: str) -> dict[str, bool | str]:
    return {
        "success": False,
        "message": f"Failed to {action} `{file_name}",
    }


def _artifact_failure(file_name: str) -> dict[str, object]:
    return dict(_failure("create", file_name))
