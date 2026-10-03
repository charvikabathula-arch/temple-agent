import os, re, json, subprocess, asyncio, requests, edge_tts, time, base64

G = os.environ["GEMINI_API_KEY"]
P = os.environ["PIXABAY_API_KEY"]
UA = {"User-Agent": "temple-agent/1.0 (personal project)"}
used = json.load(open("used.json")) if os.path.exists("used.json") else []

prompt = f"""Instagram Reel about a Telugu-audience temple mystery. Pick ONE real, well-documented fact about an Indian temple that is not in this list: {used}. Do not invent or exaggerate facts. Return only JSON with keys: topic (English), temple_name (English, full official name with city, for photo search), script (Telugu, 80 to 100 words, simple spoken conversational Telugu, short punchy sentences, shocking hook in first line, end with a question to viewers, no symbols or emojis), caption (Telugu, 2 lines), hashtags (one string), keywords (list of 4 English stock video search terms)."""

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

def wiki_images(name, limit):
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"filetype:bitmap {name}", "gsrlimit": 25,
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

def find_video(q):
    try:
        v = requests.get("https://pixabay.com/api/videos/",
                         params={"key": P, "q": q, "per_page": 5}, timeout=30).json()
        for h in v.get("hits", []):
            for size in ("medium", "small", "tiny"):
                u = h["videos"].get(size, {}).get("url")
                if u:
                    return u
    except Exception as e:
        print("pixabay ERROR:", e)
    return None

shots = [("img", u) for u in wiki_images(d.get("temple_name", d["topic"]), 8)]
print("Wikimedia images found:", len(shots))
if len(shots) < 6:
    for k in d["keywords"] + ["india temple", "ancient stone temple"]:
        if len(shots) >= 6:
            break
        u = find_video(k)
        if u:
            shots.append(("vid", u))
n = len(shots)
seg = dur / n + 0.3
frames = int(seg * 30) + 1
print("Shots:", n, "seconds each:", round(seg, 1))

GRADE = "eq=contrast=1.08:saturation=1.12,vignette=PI/5"
parts = []
for i, (kind, u) in enumerate(shots):
    try:
        if kind == "img":
            open(f"out/r{i}.jpg", "wb").write(requests.get(u, headers=UA, timeout=60).content)
            z = "z='min(zoom+0.0007,1.2)'" if i % 2 == 0 else "z='if(eq(on,1),1.2,max(zoom-0.0007,1.0))'"
            vf = (f"scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
                  f"zoompan={z}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,{GRADE}")
            subprocess.run(["ffmpeg", "-y", "-i", f"out/r{i}.jpg", "-t", str(seg), "-vf", vf,
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", f"out/c{i}.mp4"], check=True)
        else:
            open(f"out/r{i}.mp4", "wb").write(requests.get(u, timeout=60).content)
            vf = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,{GRADE}"
            subprocess.run(["ffmpeg", "-y", "-i", f"out/r{i}.mp4", "-t", str(seg), "-an", "-vf", vf,
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", f"out/c{i}.mp4"], check=True)
        parts.append(f"file 'c{i}.mp4'")
    except Exception as e:
        print("shot", i, "failed:", str(e)[:200])
if not parts:
    raise SystemExit("No video shots could be made")
open("out/list.txt", "w").write("\n".join(parts))

def ts(s):
    ms = int(round(s * 1000))
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"

chunks = []
for sent in re.split(r"(?<=[.!?\u0964])\s+", d["script"].strip()):
    w = sent.split()
    chunks += [" ".join(w[k:k+4]) for k in range(0, len(w), 4)]
total = sum(len(c) for c in chunks) or 1
t = 0.0
srt = []
for idx, c in enumerate(chunks):
    dd = dur * len(c) / total
    srt.append(f"{idx+1}\n{ts(t)} --> {ts(t+dd)}\n{c}\n")
    t += dd
open("out/subs.srt", "w", encoding="utf-8").write("\n".join(srt))

SUB = "subtitles=out/subs.srt:force_style='FontName=Noto Sans Telugu,FontSize=14,Bold=1,Outline=3,Shadow=0,Alignment=2,MarginV=55'"
if os.path.exists("music.mp3"):
    print("Mixing music.mp3")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "out/list.txt",
           "-i", "out/voice.mp3", "-stream_loop", "-1", "-i", "music.mp3",
           "-filter_complex", f"[0:v]{SUB}[v];[2:a]volume=0.12[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", "out/reel.mp4"]
else:
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "out/list.txt",
           "-i", "out/voice.mp3", "-map", "0:v", "-map", "1:a", "-vf", SUB,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "out/reel.mp4"]
subprocess.run(cmd, check=True)

credit = "\n\nPhotos: Wikimedia Commons" if any(k == "img" for k, _ in shots) else ""
json.dump({"caption": d["caption"] + "\n\n" + d["hashtags"] + credit}, open("out/post.json", "w"), ensure_ascii=False)
used.append(d["topic"])
json.dump(used, open("used.json", "w"))
