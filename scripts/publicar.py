#!/usr/bin/env python3
"""
Verifica Issues com label 'agendado' e publica nas redes indicadas pelas labels.
Labels de rede suportadas: instagram, threads, facebook, linkedin, tiktok
Rodado pelo GitHub Actions a cada 5 minutos.
"""
import os, requests, time
from datetime import datetime, timezone, timedelta

# ── Credenciais (GitHub Secrets) ──────────────────────────────────────────────
IG_TOKEN       = os.environ.get("IG_TOKEN", "")
IG_ID          = os.environ.get("IG_ID", "")
THREADS_TOKEN  = os.environ.get("THREADS_TOKEN", "")
THREADS_ID     = os.environ.get("THREADS_ID", "")
FB_TOKEN       = os.environ.get("FB_TOKEN", "")
FB_PAGE_ID     = os.environ.get("FB_PAGE_ID", "")
LINKEDIN_TOKEN = os.environ.get("LINKEDIN_TOKEN", "")
LINKEDIN_URN   = os.environ.get("LINKEDIN_URN", "")   # urn:li:person:xxx
TIKTOK_TOKEN   = os.environ.get("TIKTOK_TOKEN", "")
GH_TOKEN       = os.environ["GH_TOKEN"]
REPO           = os.environ.get("GITHUB_REPOSITORY", "felipejacoto/carrossel-slides")

GH_RAW = f"https://raw.githubusercontent.com/{REPO}/main"
API_GH = f"https://api.github.com/repos/{REPO}"
BRT    = timezone(timedelta(hours=-3))

# ── GitHub API ────────────────────────────────────────────────────────────────
def gh(method, endpoint, **kwargs):
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = getattr(requests, method)(f"{API_GH}/{endpoint}", headers=headers, **kwargs)
    return r.json()

# ── Parsear body da Issue ─────────────────────────────────────────────────────
def parse_body(body):
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

def slide_urls(pasta, total):
    return [f"{GH_RAW}/{pasta}/slide_{i:02d}.png" for i in range(1, total + 1)]

# ── Publishers ────────────────────────────────────────────────────────────────

def pub_instagram(pasta, caption, total):
    """Carrossel no Instagram via Graph API."""
    if not IG_TOKEN or not IG_ID:
        raise Exception("IG_TOKEN ou IG_ID não configurados.")
    api = "https://graph.instagram.com/v21.0"

    def call(method, endpoint, **kw):
        kw.setdefault("params", {})["access_token"] = IG_TOKEN
        r = getattr(requests, method)(f"{api}/{endpoint}", **kw)
        d = r.json()
        if "error" in d:
            raise Exception(d["error"])
        return d

    urls = slide_urls(pasta, total)
    print(f"    [{total} containers]", end=" ", flush=True)
    item_ids = []
    for url in urls:
        res = call("post", f"{IG_ID}/media", data={"image_url": url, "is_carousel_item": "true"})
        item_ids.append(res["id"])
        time.sleep(1)

    carousel = call("post", f"{IG_ID}/media", data={
        "media_type": "CAROUSEL",
        "children": ",".join(item_ids),
        "caption": caption,
    })
    time.sleep(30)
    pub = call("post", f"{IG_ID}/media_publish", data={"creation_id": carousel["id"]})
    return pub.get("id")


def pub_threads(pasta, caption, total):
    """Carrossel no Threads via Threads API."""
    if not THREADS_TOKEN or not THREADS_ID:
        raise Exception("THREADS_TOKEN ou THREADS_ID não configurados.")
    api = "https://graph.threads.net/v1.0"

    def call(method, endpoint, **kw):
        kw.setdefault("params", {})["access_token"] = THREADS_TOKEN
        r = getattr(requests, method)(f"{api}/{endpoint}", **kw)
        d = r.json()
        if "error" in d:
            raise Exception(d["error"])
        return d

    urls = slide_urls(pasta, total)
    item_ids = []
    for url in urls:
        res = call("post", f"{THREADS_ID}/threads", data={
            "media_type": "IMAGE",
            "image_url": url,
            "is_carousel_item": "true",
        })
        item_ids.append(res["id"])
        time.sleep(1)

    carousel = call("post", f"{THREADS_ID}/threads", data={
        "media_type": "CAROUSEL",
        "children": ",".join(item_ids),
        "text": caption,
    })
    time.sleep(15)
    pub = call("post", f"{THREADS_ID}/threads_publish", data={"creation_id": carousel["id"]})
    return pub.get("id")


def pub_facebook(pasta, caption, total):
    """Post com múltiplas fotos na Facebook Page."""
    if not FB_TOKEN or not FB_PAGE_ID:
        raise Exception("FB_TOKEN ou FB_PAGE_ID não configurados.")
    api = "https://graph.facebook.com/v21.0"

    def call(method, endpoint, **kw):
        kw.setdefault("params", {})["access_token"] = FB_TOKEN
        r = getattr(requests, method)(f"{api}/{endpoint}", **kw)
        d = r.json()
        if "error" in d:
            raise Exception(d["error"])
        return d

    urls = slide_urls(pasta, total)
    photo_ids = []
    for url in urls:
        res = call("post", f"{FB_PAGE_ID}/photos", data={"url": url, "published": "false"})
        photo_ids.append({"media_fbid": res["id"]})
        time.sleep(1)

    pub = call("post", f"{FB_PAGE_ID}/feed", data={
        "message": caption,
        "attached_media": str(photo_ids),
    })
    return pub.get("id")


def pub_linkedin(pasta, caption, total):
    """Post com imagens no LinkedIn (Document/carousel)."""
    if not LINKEDIN_TOKEN or not LINKEDIN_URN:
        raise Exception("LINKEDIN_TOKEN ou LINKEDIN_URN não configurados.")
    # LinkedIn aceita até 9 imagens por post
    urls = slide_urls(pasta, min(total, 9))
    headers = {
        "Authorization": f"Bearer {LINKEDIN_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    # Registrar upload de cada imagem
    image_urns = []
    for url in urls:
        # 1. Iniciar upload
        reg = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=headers, json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": LINKEDIN_URN,
                "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}],
            }
        }).json()
        upload_url = reg["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset_urn  = reg["value"]["asset"]

        # 2. Upload da imagem (download da URL pública e reupload)
        img_bytes = requests.get(url).content
        requests.put(upload_url, headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"}, data=img_bytes)
        image_urns.append(asset_urn)
        time.sleep(1)

    # 3. Publicar post com imagens
    media = [{"status": "READY", "description": {"text": ""}, "media": urn, "title": {"text": ""}} for urn in image_urns]
    payload = {
        "author": LINKEDIN_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": caption},
                "shareMediaCategory": "IMAGE",
                "media": media,
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    pub = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload).json()
    return pub.get("id")


def pub_tiktok(pasta, caption, total):
    """Carrossel de fotos no TikTok (Photo Mode)."""
    if not TIKTOK_TOKEN:
        raise Exception("TIKTOK_TOKEN não configurado.")
    urls = slide_urls(pasta, min(total, 35))  # TikTok permite até 35 fotos
    headers = {
        "Authorization": f"Bearer {TIKTOK_TOKEN}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {
        "post_info": {
            "title": caption[:150],  # TikTok limita título
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_images": urls,
            "photo_cover_index": 0,
        },
        "media_type": "PHOTO",
    }
    r = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/content/init/",
        headers=headers, json=payload
    ).json()
    if r.get("error", {}).get("code", "ok") != "ok":
        raise Exception(r["error"])
    return r.get("data", {}).get("publish_id")


# ── Mapa de redes ─────────────────────────────────────────────────────────────
PUBLISHERS = {
    "instagram": pub_instagram,
    "threads":   pub_threads,
    "facebook":  pub_facebook,
    "linkedin":  pub_linkedin,
    "tiktok":    pub_tiktok,
}

# ── Main ──────────────────────────────────────────────────────────────────────
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
        labels = [l["name"] for l in issue.get("labels", [])]
        redes  = [r for r in PUBLISHERS if r in labels]

        print(f"\nIssue #{num}: {issue['title']}")
        print(f"  Redes: {', '.join(redes) if redes else 'nenhuma rede configurada'}")

        if not redes:
            continue

        try:
            meta      = parse_body(issue["body"] or "")
            scheduled = datetime.fromisoformat(meta["horario"])
            diff      = (scheduled - now).total_seconds()
            print(f"  Agendado: {scheduled.strftime('%d/%m %H:%M')} BRT")

            if diff > 0:
                print(f"  Publica em {int(diff//60)}m {int(diff%60)}s.")
                continue

            # Publicar em cada rede selecionada
            resultados = []
            for rede in redes:
                print(f"  [{rede.upper()}] Publicando...", end=" ", flush=True)
                try:
                    media_id = PUBLISHERS[rede](meta["pasta"], meta["caption"], meta["slides"])
                    print(f"ok (ID: {media_id})")
                    resultados.append(f"✅ {rede}: `{media_id}`")
                except Exception as e:
                    print(f"ERRO: {e}")
                    resultados.append(f"❌ {rede}: {e}")

            # Determinar status geral
            tem_erro   = any(r.startswith("❌") for r in resultados)
            tem_sucesso = any(r.startswith("✅") for r in resultados)

            if tem_sucesso and tem_erro:
                novo_label = ["publicado", "falhou"]   # parcialmente publicado
            elif tem_sucesso:
                novo_label = ["publicado"]
            else:
                novo_label = ["falhou"]                # todas as redes falharam

            # Fechar Issue e registrar resultado
            gh("post", f"issues/{num}/labels", json={"labels": novo_label})
            gh("patch", f"issues/{num}", json={
                "state": "closed",
                "body": issue["body"] + f"\n\n---\nProcessado em {now.strftime('%d/%m/%Y %H:%M')} BRT\n" + "\n".join(resultados),
            })
            requests.delete(
                f"{API_GH}/issues/{num}/labels/agendado",
                headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"},
            )
            print(f"  Issue #{num} fechada com: {novo_label}")

        except Exception as e:
            print(f"  ERRO GERAL: {e}")
            gh("post", f"issues/{num}/labels", json={"labels": ["falhou"]})
            gh("patch", f"issues/{num}", json={"state": "closed"})
            requests.delete(
                f"{API_GH}/issues/{num}/labels/agendado",
                headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"},
            )
            gh("post", f"issues/{num}/comments", json={"body": f"❌ Erro geral: {e}"})

if __name__ == "__main__":
    main()
