"""Testes das heurísticas de OCR (sem depender do engine RapidOCR)."""
from __future__ import annotations

from aeye.ocr import needs_vlm


def test_vazio_sugere_vlm() -> None:
    assert needs_vlm("") is True


def test_pouco_texto_sugere_vlm() -> None:
    assert needs_vlm("abc") is True  # < 8 caracteres
    assert needs_vlm("a b c") is True


def test_so_simbolos_sugere_vlm() -> None:
    assert needs_vlm("---___!!!") is True


def test_texto_real_nao_sugere_vlm() -> None:
    assert needs_vlm("Fatura número 12345 de 10/10/2025") is False
    assert needs_vlm("Olá, isto é um parágrafo com bastante texto.") is False
