@echo off
chcp 65001 >nul
title 注入 RenderDoc 到 MuMu
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0inject_renderdoc.ps1"
