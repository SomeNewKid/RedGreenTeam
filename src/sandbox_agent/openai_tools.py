"""OpenAI Agents SDK adapters for Sandbox Agent tools."""

from __future__ import annotations

from agents import function_tool

from .tools import (
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
    save_html_document,
    save_image,
    save_shared_file,
    save_shared_image_artifact,
    validate_html5_element,
)

create_solution_skeleton_tool = function_tool(create_solution_skeleton)
get_answer_format_tool = function_tool(get_answer_format)
get_active_items_tool = function_tool(get_active_items)
generate_image_artifact_tool = function_tool(generate_image_artifact)
generate_image_tool = function_tool(generate_image)
get_html_element_name_tool = function_tool(get_html_element_name)
get_test_assessment_tool = function_tool(get_test_assessment)
jina_read_url_tool = function_tool(jina_read_url)
microsoft_code_sample_search_tool = function_tool(microsoft_code_sample_search)
microsoft_docs_fetch_tool = function_tool(microsoft_docs_fetch)
microsoft_docs_search_tool = function_tool(microsoft_docs_search)
request_code_update_tool = function_tool(request_code_update)
request_solution_stub_tool = function_tool(request_solution_stub)
request_test_creation_tool = function_tool(request_test_creation)
run_red_green_loop_tool = function_tool(run_red_green_loop)
run_python_script_tool = function_tool(run_python_script)
save_answer_tool = function_tool(save_answer)
save_html_document_tool = function_tool(save_html_document)
save_image_tool = function_tool(save_image)
read_shared_file_tool = function_tool(read_shared_file)
save_shared_file_tool = function_tool(save_shared_file)
save_shared_image_artifact_tool = function_tool(save_shared_image_artifact)
validate_html5_element_tool = function_tool(validate_html5_element)
