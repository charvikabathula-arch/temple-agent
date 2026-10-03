import os, json, subprocess, asyncio, requests, edge_tts, time, base64

G = os.environ["GEMINI_API_KEY"]
P = os.environ["PIXABAY_API_KEY"]
UA = {"User-Agent": "temple-agent/1.0 (personal project)"}
used = json.load(open("used.json")) if os.path.exists("used.json") else []

prompt = f"""Instagram Reel about a Telugu-audience temple mystery. Pick ONE real, well-documented fact about an Indian temple that is not in this list: {used}. Do not invent or exaggerate facts. Return only JSON with keys: topic (English), temple_name (English, full official name with city, for photo search), script (Telugu, 90 to 110 words, simple spoken conversational Telugu, short sentences, strong hook in first line, no symbols or emojis), caption (Telugu, 2 lines), hashtags (one string), keywords (list of 4 English stock video search terms)."""

MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
TTS_MODELS = ["gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview", "gemini-3.8-flash-tts"]

d = None
for attempt in range(4):
    for m in MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={G}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json"}},
                timeout=60)
            j = r.json()
        except Exception as e:
            print(m, "ERROR:", e)
            continue
        if "candidates" in j:
            d = json.loads(j["candidates"][0]["content"]["parts"][0]["text"])
            print("Used model:", m)
            break
        print(m, "FAILED:", r.status_code, str(j)[:200])
    if d:
        break
    time.sleep(30)
if d is None:
    raise SystemExit("Gemini failed, see message above")

os.makedirs("out", exist_ok=True)

def gemini_tts(text):
    for m in TTS_MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={G}",
                json={"contents": [{"parts": [{"text": text}]}],
                      "generationConfig": {"responseModalities": ["AUDIO"],
                                           "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}},
                timeout=120)
            j = r.json()
            b64 = j["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            open("out/voice.pcm", "wb").write(base64.b64decode(b64))
            subprocess.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                            "-i", "out/voice.pcm", "out/voice.mp3"], check=True)
            print("TTS model:", m)
            return True
        except Exception as e:
            print(m, "TTS FAILED:", str(e)[:200])
    return False

if not gemini_tts(d["script"]):
    print("Falling back to edge-tts")
    asyncio.run(edge_tts.Communicate(d["script"], "te-IN-ShrutiNeural").save("out/voice.mp3"))

dur = float(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "csv=p=0", "out/voice.mp3"]).decode().strip())
n = len(d["keywords"])
seg = dur / n + 0.5

def wiki_images(name, limit):
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"filetype:bitmap {name}", "gsrlimit": 15,
            "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 1600,
            "format": "json"}, headers=UA, timeout=30).json()
        pages = sorted(r.get("query", {}).get("pages", {}).values(), key=lambda x: x.get("index", 0))
        out = []
        for p in pages:
            ii = p.get("imageinfo", [{}])[0]
            if ii.get("mime") == "image/jpeg" and ii.get("width", 0) >= 900 and ii.get("thumburl"):
                out.append(ii["thumburl"])
        return out[:limit]
    except Exception as e:
        print("wiki ERROR:", e)
        return []

imgs = wiki_images(d.get("temple_name", d["topic"]), n)
print("Wikimedia images found:", len(imgs))

def find_video(q):
    v = requests.get("https://pixabay.com/api/videos/",
                     params={"key": P, "q": q, "per_page": 5}, timeout=30).json()
    for h in v.get("hits", []):
        for size in ("medium", "small", "tiny"):
            u = h["videos"].get(size, {}).get("url")
            if u:
                return u
    return None

frames = int(seg * 30) + 1
parts = []
for i, k in enumerate(d["keywords"]):
    done = False
    if i < len(imgs):
        try:
            open(f"out/r{i}.jpg", "wb").write(requests.get(imgs[i], headers=UA, timeout=60).content)
            subprocess.run(["ffmpeg", "-y", "-i", f"out/r{i}.jpg", "-t", str(seg),
                            "-vf", f"scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,zoompan=z='min(zoom+0.0006,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", f"out/c{i}.mp4"], check=True)
            done = True
        except Exception as e:
            print("image seg failed:", e)
    if not done:
        url = find_video(k) or find_video("india temple")
        open(f"out/r{i}.mp4", "wb").write(requests.get(url, timeout=60).content)
        subprocess.run(["ffmpeg", "-y", "-i", f"out/r{i}.mp4", "-t", str(seg), "-an",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", f"out/c{i}.mp4"], check=True)
    parts.append(f"file 'c{i}.mp4'")

open("out/list.txt", "w").write("\n".join(parts))
subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "out/list.txt",
                "-i", "out/voice.mp3", "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "out/reel.mp4"], check=True)

credit = "\n\nPhotos: Wikimedia Commons" if imgs else ""
json.dump({"caption": d["caption"] + "\n\n" + d["hashtags"] + credit}, open("out/post.json", "w"), ensure_ascii=False)
used.append(d["topic"])
json.dump(used, open("used.json", "w"))
