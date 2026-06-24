"""builder_components.util — single-concern helpers shared across the tooling modules.

Each module here holds one canonical copy of a helper that was previously duplicated across the
standalone scripts (frontmatter parsing, project-root resolution, the LF-forced file writer).
Splitting the monoliths into submodules turns these former in-file helpers into genuinely shared
utilities, so they live here once and every consumer imports them.
"""
