"""Deol Tech web application."""

from __future__ import annotations

from .app import Platform, build_app, run
from .server import Request, Response, WebApp, serve

__all__ = ["Platform", "build_app", "run", "WebApp", "Request", "Response", "serve"]
