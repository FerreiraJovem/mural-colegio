"""Gera o site do mural a partir da pasta midia/.

- Gira imagens e videos para a TV em pe (config.json -> rotacao).
- Cria site/playlist.json, que o app do Roku le.

Nome do arquivo controla tudo (opcional):
  01_aviso.jpg                -> ordem pelo nome
  02_feira_15s.jpg            -> fica 15 segundos na tela
  03_ate-2026-11-10_prova.jpg -> some depois de 10/11/2026
  04_de-2026-11-20_festa.mp4  -> so aparece a partir de 20/11/2026
Arquivos que comecam com _ ou . sao ignorados (rascunho).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

RAIZ = Path(__file__).resolve().parent
MIDIA = RAIZ / "midia"
SITE = RAIZ / "site"
CACHE = RAIZ / ".cache"
IMG = {".jpg", ".jpeg", ".png", ".webp"}
VID = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
W, H = 1920, 1080

RE_DE = re.compile(r"(?:^|[_\s])de-(\d{4}-\d{2}-\d{2})", re.I)
RE_ATE = re.compile(r"(?:^|[_\s])ate-(\d{4}-\d{2}-\d{2})", re.I)
RE_DUR = re.compile(r"(?:^|[_\-\s])(\d{1,3})s(?=$|[_\-\s])", re.I)

# rotacao (graus, sentido anti-horario) -> filtro do ffmpeg
TRANSPOSE = {0: "", 90: "transpose=2,", 180: "transpose=1,transpose=1,", 270: "transpose=1,"}


def base_url(cfg):
    if cfg.get("base_url"):
        return cfg["base_url"].rstrip("/") + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        sys.exit("Defina base_url no config.json (ou rode pelo GitHub Actions).")
    dono, nome = repo.split("/", 1)
    dono = dono.lower()
    if nome.lower() == f"{dono}.github.io":
        return f"https://{dono}.github.io/"
    return f"https://{dono}.github.io/{nome}/"


def hash_arquivo(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()[:12]


def processar_imagem(src, dst, rot):
    img = Image.open(src)
    img = ImageOps.exif_transpose(img).convert("RGB")
    if rot:
        img = img.rotate(rot, expand=True)  # anti-horario
    img = ImageOps.pad(img, (W, H), color="black", method=Image.LANCZOS)
    img.save(dst, "JPEG", quality=88, optimize=True)


def processar_video(src, dst, rot):
    vf = (
        f"{TRANSPOSE[rot]}scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst),
    ]
    subprocess.run(cmd, check=True)


def main():
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    rot = int(cfg.get("rotacao", 90)) % 360
    if rot not in TRANSPOSE:
        sys.exit("rotacao precisa ser 0, 90, 180 ou 270")
    dur_padrao = int(cfg.get("duracao_padrao", 10))
    base = base_url(cfg)

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "m").mkdir(parents=True)
    CACHE.mkdir(exist_ok=True)

    itens = []
    arquivos = sorted(
        (p for p in MIDIA.iterdir() if p.is_file() and not p.name.startswith((".", "_"))),
        key=lambda p: p.name.lower(),
    )
    for src in arquivos:
        ext = src.suffix.lower()
        if ext not in IMG and ext not in VID:
            print(f"ignorado (formato): {src.name}")
            continue
        h = hash_arquivo(src)
        video = ext in VID
        saida_nome = f"{h}_r{rot}.{'mp4' if video else 'jpg'}"
        cache = CACHE / saida_nome
        if not cache.exists():
            print(f"processando: {src.name}")
            (processar_video if video else processar_imagem)(src, cache, rot)
        shutil.copy2(cache, SITE / "m" / saida_nome)

        item = {"tipo": "video" if video else "imagem", "url": base + "m/" + saida_nome, "nome": src.name}
        stem = src.stem
        if (m := RE_DE.search(stem)):
            item["de"] = m.group(1)
        if (m := RE_ATE.search(stem)):
            item["ate"] = m.group(1)
        if not video:
            m = RE_DUR.search(stem)
            item["duracao"] = int(m.group(1)) if m else dur_padrao
        itens.append(item)

    playlist = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duracao_padrao": dur_padrao,
        "itens": itens,
    }
    (SITE / "playlist.json").write_text(json.dumps(playlist, ensure_ascii=False, indent=1), encoding="utf-8")
    (SITE / ".nojekyll").write_text("")
    (SITE / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Mural</title>"
        f"<p>Mural publicado. {len(itens)} itens. <a href='playlist.json'>playlist.json</a></p>",
        encoding="utf-8",
    )

    # limpa do cache o que nao esta mais na pasta
    usados = {Path(i["url"]).name for i in itens}
    for c in CACHE.iterdir():
        if c.name not in usados:
            c.unlink()
    print(f"OK: {len(itens)} itens -> {base}playlist.json")


if __name__ == "__main__":
    main()
