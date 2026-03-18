#!/usr/bin/env python3
"""
contemplay_update.py — Plugin de atualização do Banco de Cotas
=============================================================
Uso:
    python contemplay_update.py --video caminho/do/video.mp4

O script:
  1. Extrai frames do vídeo (ffmpeg)
  2. Envia frames para a API Claude (claude-sonnet-4-20250514) para OCR
  3. Substitui o bloco COTAS_DATA em public/index.html
  4. Faz commit + push para o GitHub
  5. Vercel detecta o push e redeploy automaticamente

Dependências:
    pip install anthropic requests python-dotenv

Variáveis de ambiente (.env):
    ANTHROPIC_API_KEY=sk-...
    GITHUB_TOKEN=ghp_...
    GITHUB_REPO=usuario/contemplay   (ex: nikollas/contemplay)
    GITHUB_BRANCH=main
"""

import os
import sys
import json
import base64
import re
import argparse
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# ── 1. DEPENDÊNCIAS ──────────────────────────────────────────────────────────
try:
    import anthropic
except ImportError:
    sys.exit("❌ Instale: pip install anthropic")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env opcional

# ── 2. CONFIG ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO       = os.getenv("GITHUB_REPO", "")   # ex: nikollas/contemplay
GITHUB_BRANCH     = os.getenv("GITHUB_BRANCH", "main")

HTML_FILE = Path(__file__).parent / "public" / "index.html"
DATA_START_MARKER = "// COTAS_DATA_START"
DATA_END_MARKER   = "// COTAS_DATA_END"

# ── 3. EXTRAÇÃO DE FRAMES ────────────────────────────────────────────────────
def extract_frames(video_path: str, fps: str = "1/3") -> list[str]:
    """Extrai frames do vídeo a cada 3 segundos usando ffmpeg."""
    print(f"🎬 Extraindo frames de: {video_path}")
    tmpdir = tempfile.mkdtemp(prefix="contemplay_")
    out_pattern = os.path.join(tmpdir, "frame_%04d.jpg")

    result = subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"fps={fps}", "-q:v", "2", out_pattern, "-y"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        shutil.rmtree(tmpdir)
        sys.exit(f"❌ ffmpeg falhou:\n{result.stderr}")

    frames = sorted(Path(tmpdir).glob("frame_*.jpg"))
    print(f"   → {len(frames)} frames extraídos")
    return [str(f) for f in frames], tmpdir


# ── 4. OCR VIA CLAUDE API ────────────────────────────────────────────────────
SYSTEM_PROMPT = """Você analisa frames de um vídeo do aplicativo Banco de Cotas da Ademicon.
Extraia TODAS as cotas visíveis. Para cada cota retorne exatamente:
- g: grupo (string)
- t: tipo ("Imóveis" ou "Veículos")
- c: crédito disponível (float, sem R$)
- e: valor de entrada (float, sem R$)
- p: valor da parcela mensal (float, sem R$)
- pr: prazo restante em meses (int)

Retorne SOMENTE JSON válido, sem markdown, sem explicação:
{"total_banco": <int do contador exibido>, "cotas": [...]}

Deduplicar cotas iguais. Se o contador total aparecer na tela, incluir em total_banco."""

def ocr_frames_claude(frame_paths: list[str]) -> dict:
    """Envia todos os frames para o Claude e extrai os dados das cotas."""
    if not ANTHROPIC_API_KEY:
        sys.exit("❌ ANTHROPIC_API_KEY não definida")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print(f"🤖 Enviando {len(frame_paths)} frames para Claude OCR...")

    # Montar conteúdo com todos os frames
    content = []
    for path in frame_paths:
        with open(path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
        })

    content.append({"type": "text", "text": "Analise todos os frames e retorne o JSON com todas as cotas extraídas."})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.content[0].text.strip()
    # Limpar possível markdown
    raw = re.sub(r"```json\s*|\s*```", "", raw).strip()

    try:
        data = json.loads(raw)
        print(f"   → {len(data['cotas'])} cotas extraídas (total banco: {data.get('total_banco','?')})")
        return data
    except json.JSONDecodeError as e:
        sys.exit(f"❌ Claude retornou JSON inválido:\n{raw[:500]}\n\nErro: {e}")


# ── 5. ATUALIZAR HTML ────────────────────────────────────────────────────────
def update_html(cotas_data: dict, video_name: str) -> None:
    """Substitui o bloco COTAS_DATA no index.html."""
    if not HTML_FILE.exists():
        sys.exit(f"❌ Arquivo não encontrado: {HTML_FILE}")

    cotas_data["updated"] = datetime.now().strftime("%Y-%m-%d")
    cotas_data["source"]  = Path(video_name).name

    json_str    = json.dumps(cotas_data, ensure_ascii=False, separators=(",", ":"))
    novo_bloco  = f"{DATA_START_MARKER}\nconst COTAS_DATA = {json_str};\n{DATA_END_MARKER}"

    html = HTML_FILE.read_text(encoding="utf-8")
    pattern = rf"{re.escape(DATA_START_MARKER)}.*?{re.escape(DATA_END_MARKER)}"

    if not re.search(pattern, html, re.DOTALL):
        sys.exit(f"❌ Marcadores não encontrados em {HTML_FILE}.\n"
                 f"O HTML precisa conter:\n  {DATA_START_MARKER}\n  ...\n  {DATA_END_MARKER}")

    novo_html = re.sub(pattern, novo_bloco, html, flags=re.DOTALL)
    HTML_FILE.write_text(novo_html, encoding="utf-8")
    print(f"✅ {HTML_FILE.name} atualizado — {len(cotas_data['cotas'])} cotas")


# ── 6. GITHUB PUSH ───────────────────────────────────────────────────────────
def git_push(video_name: str, n_cotas: int) -> None:
    """Commit + push para o GitHub."""
    repo_root = HTML_FILE.parent.parent

    def run(cmd, **kw):
        r = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, **kw)
        if r.returncode != 0:
            print(f"⚠️  {' '.join(cmd)}\n{r.stderr.strip()}")
        return r

    # Configurar remote com token se GITHUB_REPO definido
    if GITHUB_TOKEN and GITHUB_REPO:
        remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        run(["git", "remote", "set-url", "origin", remote_url])

    hoje   = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg    = f"feat: atualiza banco de cotas — {n_cotas} cotas · {hoje}"
    source = Path(video_name).name

    run(["git", "add", "public/index.html"])
    result = run(["git", "commit", "-m", msg])

    if "nothing to commit" in result.stdout + result.stderr:
        print("ℹ️  Nenhuma alteração para commitar.")
        return

    push = run(["git", "push", "origin", GITHUB_BRANCH])
    if push.returncode == 0:
        print(f"🚀 Push realizado → {GITHUB_REPO} [{GITHUB_BRANCH}]")
        print(f"   Vercel irá redeploy automaticamente em ~30s")
    else:
        print(f"❌ Push falhou. Verifique GITHUB_TOKEN e GITHUB_REPO.")
        print(push.stderr)


# ── 7. MAIN ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Contemplay — Atualiza banco de cotas a partir de vídeo"
    )
    parser.add_argument("--video", required=True, help="Caminho do vídeo MP4")
    parser.add_argument("--fps",   default="1/3",  help="Frequência de extração de frames (padrão: 1/3)")
    parser.add_argument("--no-push", action="store_true", help="Não fazer git push (só atualiza o HTML)")
    args = parser.parse_args()

    if not Path(args.video).exists():
        sys.exit(f"❌ Vídeo não encontrado: {args.video}")

    # 1. Extrair frames
    frames, tmpdir = extract_frames(args.video, fps=args.fps)

    try:
        # 2. OCR via Claude
        cotas_data = ocr_frames_claude(frames)

        # 3. Atualizar HTML
        update_html(cotas_data, args.video)

        # 4. Push para GitHub
        if not args.no_push:
            git_push(args.video, len(cotas_data["cotas"]))
        else:
            print("ℹ️  --no-push ativo: HTML atualizado mas sem git push.")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n✅ Concluído!")
    print(f"   Cotas no banco: {len(cotas_data['cotas'])}")
    print(f"   Data:           {cotas_data['updated']}")
    print(f"   Fonte:          {cotas_data['source']}")


if __name__ == "__main__":
    main()
