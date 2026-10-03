import os, json, subprocess, asyncio, requests, edge_tts

G = os.environ["GEMINI_API_KEY"]
P = os.environ["PIXABAY_API_KEY"]
used = json.load(open("used.json")) if os.path.exists("used.json") else []

prompt = f"""Instagram Reel about a Telugu-audience temple mystery. Pick ONE real, well-documented fact about an Indian temple that is not in this list: {used}. Do not invent or exaggerate facts. Return only JSON with keys: topic (English), script (Telugu, 90 to 110 words, strong hook in first line), caption (Telugu, 2 lines), hashtags (one string), keywords (list of 4 English stock video search terms)."""

r = requests.post(
    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={G}",
    json={"contents": [{"parts": [{"text": prompt}]}],
          "generationConfig": {"responseMimeType": "application/json"}})
d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])

os.makedirs("out", exist_ok=True)
asyncio.run(edge_tts.Communicate(d["script"], "te-IN-ShrutiNeural").save("out/voice.mp3"))

dur = float(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "csv=p=0", "out/voice.mp3"]).decode().strip())
n = len(d["keywords"])
seg = dur / n + 0.5

def find_video(q):
    v = requests.get("https://pixabay.com/api/videos/",
                     params={"key": P, "q": q, "per_page": 5}).json()
    for h in v.get("hits", []):
        for size in ("medium", "small", "tiny"):
            u = h["videos"].get(size, {}).get("url")
            if u:
                return u
    return None

parts = []
for i, k in enumerate(d["keywords"]):
    url = find_video(k) or find_video("india temple")
    open(f"out/r{i}.mp4", "wb").write(requests.get(url).content)
    subprocess.run(["ffmpeg", "-y", "-i", f"out/r{i}.mp4", "-t", str(seg), "-an",
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", f"out/c{i}.mp4"], check=True)
    parts.append(f"file 'c{i}.mp4'")

open("out/list.txt", "w").write("\n".join(parts))
subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "out/list.txt",
                "-i", "out/voice.mp3", "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "out/reel.mp4"], check=True)

json.dump({"caption": d["caption"] + "\n\n" + d["hashtags"]}, open("out/post.json", "w"), ensure_ascii=False)
used.append(d["topic"])
json.dump(used, open("used.json", "w"))
