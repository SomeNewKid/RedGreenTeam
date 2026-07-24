"""Create and inspect Docker sandbox container images."""

from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which

from .models import (
    AgentImageConfiguration,
    DockerConfiguration,
    DockerImageResult,
    DockerImageStatus,
)

_DOCKER_EXECUTABLE = "docker"


def ensure_base_image(configuration: DockerConfiguration) -> DockerImageResult:
    """Create the Docker sandbox base image if it is missing."""
    return _ensure_image(
        configuration,
        configuration.profile.image_name,
        configuration.dockerfile_path,
        configuration.profile.image_build_arguments,
    )


def ensure_base_images(
    configuration: DockerConfiguration,
) -> tuple[DockerImageResult, ...]:
    """Create all Docker sandbox agent images if they are missing."""
    if not configuration.agent_image_configurations:
        return (ensure_base_image(configuration),)

    results = []
    seen_image_names = set()
    for image_configuration in configuration.agent_image_configurations:
        if image_configuration.profile.image_name in seen_image_names:
            continue

        seen_image_names.add(image_configuration.profile.image_name)
        results.append(_ensure_agent_image(configuration, image_configuration))

    return tuple(results)


def _ensure_agent_image(
    configuration: DockerConfiguration,
    image_configuration: AgentImageConfiguration,
) -> DockerImageResult:
    return _ensure_image(
        configuration,
        image_configuration.profile.image_name,
        image_configuration.dockerfile_path,
        image_configuration.profile.image_build_arguments,
    )


def _ensure_image(
    configuration: DockerConfiguration,
    image_name: str,
    dockerfile_path: Path,
    image_build_arguments: tuple[str, ...],
) -> DockerImageResult:
    if not dockerfile_path.exists():
        return DockerImageResult(
            status=DockerImageStatus.DOCKERFILE_MISSING,
            image_name=image_name,
            dockerfile_path=dockerfile_path,
        )

    if which(_DOCKER_EXECUTABLE) is None:
        return DockerImageResult(
            status=DockerImageStatus.DOCKER_MISSING,
            image_name=image_name,
            dockerfile_path=dockerfile_path,
        )

    if _image_exists(image_name):
        return DockerImageResult(
            status=DockerImageStatus.EXISTS,
            image_name=image_name,
            dockerfile_path=dockerfile_path,
        )

    build_command = _build_image_command(
        configuration,
        image_name,
        dockerfile_path,
        image_build_arguments,
    )
    build_result = subprocess.run(
        build_command,
        cwd=configuration.build_context,
        check=False,
    )

    if build_result.returncode != 0:
        return DockerImageResult(
            status=DockerImageStatus.BUILD_FAILED,
            image_name=image_name,
            dockerfile_path=dockerfile_path,
            command=build_command,
        )

    return DockerImageResult(
        status=DockerImageStatus.CREATED,
        image_name=image_name,
        dockerfile_path=dockerfile_path,
        command=build_command,
    )


def _image_exists(image_name: str) -> bool:
    inspect_command = [
        _DOCKER_EXECUTABLE,
        "image",
        "inspect",
        image_name,
    ]
    result = subprocess.run(
        inspect_command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _build_image_command(
    configuration: DockerConfiguration,
    image_name: str,
    dockerfile_path: Path,
    image_build_arguments: tuple[str, ...],
) -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        image_name,
        *image_build_arguments,
        str(configuration.build_context),
    ]
