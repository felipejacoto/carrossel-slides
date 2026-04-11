#!/usr/bin/env python3
"""
Verifica Issues com label 'agendado' e publica no Instagram quando chega a hora.
Rodado pelo GitHub Actions a cada 5 minutos.
"""
import os, requests, time
from datetime import datetime, timezone, timedelta

IG_TOKEN = os.environ["IG_TOKEN"]
IG_ID    = os.environ["IG_ID"]
GH_TOKEN = os.environ["GH_TOKEN"]
REPO     = os.environ.get("GITHUB_REPOSITORY", "felipejacoto/carrossel-slides")

API_IG = "https://graph.instagram.com/v21.0"
API_GH = f"https://api.github.com/repos/{REPO}"
GH_RAW = f"https://raw.githubusercontent.com/{REPO}/main"
BRT    = timezone(timedelta(hours=-3))

def gh(method, endpoint, **kwargs):
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = getattr(requests, method)(f"{API_GH}/{endpoint}", headers=headers, **kwargs)
    return r.json()

def ig(method, endpoint, **kwargs):
    kwargs.setdefault("params", {})["access_token"] = IG_TOKEN
    r = getattr(requests, method)(f"{API_IG}/{endpoint}", **kwargs)
    data = r.json()
    if "error" in data:
        raise Exception(f"{data['error']}")
    return data

def parse_body(body):
    """Extrai pasta, horario, slides e caption do body da Issue."""
    meta = {"slides": 7}
    caption_lines = []
    in_caption = False
    for line in body.strip().split("\n"):
        if line.startswith("pasta:"):
            meta["pasta"] = line.split(":", 1)[1].strip()
        elif line.startswith("horario:"):
            meta["horario"] = line.split(":", 1)[1].strip()
        elif line.startswith("slides:"):
            meta["slides"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("caption:"):
            in_caption = True
        elif in_caption:
            caption_lines.append(line)
    meta["caption"] = "\n".join(caption_lines).strip()
    return meta

def publicar(pasta, caption, total):
    slides = [f"{GH_RAW}/{pasta}/slide_{i:02d}.png" for i in range(1, total + 1)]

    print(f"  Criando {total} containers...")
    item_ids = []
    for i, url in enumerate(slides, 1):
        res = ig("post", f"{IG_ID}/media", data={
            "image_url": url,
            "is_carousel_item": "true",
        })
        item_ids.append(res["id"])
        print(f"    slide_{i:02d}: ok")
        time.sleep(1)

    print("  Criando container do carousel...")
    carousel = ig("post", f"{IG_ID}/media", data={
        "media_type": "CAROUSEL",
        "children": ",".join(item_ids),
        "caption": caption,
    })
    print(f"    ID: {carousel['id']}")

    print("  Aguardando 30s para processamento...")
    time.sleep(30)

    print("  Publicando...")
    pub = ig("post", f"{IG_ID}/media_publish", data={"creation_id": carousel["id"]})
    return pub.get("id")

def main():
    now = datetime.now(BRT)
    print(f"[{now.strftime('%d/%m/%Y %H:%M')} BRT] Verificando fila...")

    issues = gh("get", "issues", params={"labels": "agendado", "state": "open", "per_page": 50})

    if isinstance(issues, dict) and "message" in issues:
        print(f"Erro GitHub API: {issues['message']}")
        return

    if not issues:
        print("Nenhum post agendado.")
        return

    print(f"{len(issues)} post(s) na fila.")

    for issue in issues:
        num = issue["number"]
        print(f"\nIssue #{num}: {issue['title']}")
        try:
            meta = parse_body(issue["body"] or "")
            scheduled = datetime.fromisoformat(meta["horario"])
            diff = (scheduled - now).total_seconds()

            print(f"  Agendado: {scheduled.strftime('%d/%m %H:%M')} BRT")

            if diff <= 0:
                print("  Publicando agora...")
                media_id = publicar(meta["pasta"], meta["caption"], meta["slides"])
                print(f"  Publicado! Media ID: {media_id}")

                # Fechar Issue e marcar como publicado
                gh("post", f"issues/{num}/labels", json={"labels": ["publicado"]})
                gh("patch", f"issues/{num}", json={
                    "state": "closed",
                    "body": issue["body"] + f"\n\n---\n✅ Publicado em {now.strftime('%d/%m/%Y %H:%M')} BRT\nMedia ID: `{media_id}`",
                })
                requests.delete(
                    f"{API_GH}/issues/{num}/labels/agendado",
                    headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"},
                )
                print(f"  Issue #{num} fechada.")
            else:
                mins = int(diff // 60)
                secs = int(diff % 60)
                print(f"  Publica em {mins}m {secs}s.")

        except Exception as e:
            print(f"  ERRO: {e}")
            gh("post", f"issues/{num}/comments", json={"body": f"Erro ao publicar: {e}"})

if __name__ == "__main__":
    main()
