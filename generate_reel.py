import os
import time
import json
import random
import asyncio
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from google import genai

# ============ SETTINGS (easy things to tweak) ============
GEMINI_MODEL = "gemini-3.8-flash"         # main model
FALLBACK_MODEL = "gemini-2.5-flash-lite"  # used if the main model keeps failing
VOICE = "en-US-AndrewNeural"              # try en-US-AriaNeural, en-US-GuyNeural, en-GB-RyanNeural
VOICE_RATE = "+15%"                       # faster = bigger number, e.g. +25%
CAPTION_FONT_SIZE = 110                   # bigger number = bigger captions
WORDS_PER_CAPTION = 3                     # how many words show at once
HIGHLIGHT_COLOR = (255, 214, 0)           # yellow key word
BRAND_TEXT = "BizEaseAI"
MUSIC_FILE = "music.mp3"                  # must be in the repo's main folder
MUSIC_VOLUME = 0.12                       # lower = quieter (0.05 to 0.25)
PAD_AFTER_LINE = 0.15                     # tiny pause after each line (seconds)
# =========================================================

W, H = 1080, 1920
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
OUT = "output"
os.makedirs(OUT, exist_ok=True)

TOPICS = [
    "using AI to reply to customer messages faster",
    "using AI to write social media posts in minutes",
    "using AI to follow up with leads automatically",
    "using AI to summarise long emails and documents",
    "using AI to create a simple weekly content plan",
    "using AI to write product descriptions",
    "using AI to draft quotes and proposals",
    "saving 5 hours a week with small automations",
    "using AI to answer common customer questions",
    "using AI to brainstorm business ideas",
]


def get_script():
    topic = random.choice(TOPICS)
    prompt = f"""
You write viral Instagram Reel scripts for a brand called {BRAND_TEXT}, which helps
small business owners save time with simple AI tools.

Topic: {topic}

Return ONLY JSON in exactly this shape:
{{
  "title": "short title",
  "scenes": [
    {{"text": "spoken line", "search": "two word stock video search"}}
  ],
  "caption": "Instagram caption, 2-3 sentences, friendly, ends with a question",
  "hashtags": "#smallbusiness #ai #productivity"
}}

Rules:
- 7 scenes total.
- Scene 1 is a scroll-stopping hook: a bold claim, a shocking number or a direct
  question. Example style: "You're wasting 10 hours a week on this." Under 9 words.
- Scenes 2 to 6 give one clear, practical tip each, in a punchy, energetic tone.
- Scene 7 is a call to action: follow for more.
- Each line is under 12 words, plain English, no jargon, no emojis.
- "search" is 1 to 3 simple words describing a visual that matches the line, using
  common stock footage subjects, such as "business owner", "laptop typing",
  "phone messages", "coffee shop", "office team", "typing keyboard", "happy customer".
"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    last_error = None
    for attempt in range(6):
        model = GEMINI_MODEL if attempt < 4 else FALLBACK_MODEL
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return json.loads(resp.text)
        except Exception as e:
            last_error = e
            print(f"Attempt {attempt + 1} failed ({model}): {e}")
            time.sleep(15 * (attempt + 1))
    raise last_error


def pixabay_search(query):
    key = os.environ["PIXABAY_API_KEY"]
    r = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": query[:90], "per_page": 20, "safesearch": "true"},
        timeout=30,
    )
    if not r.ok:
        print("Pixabay error:", r.status_code, r.text[:200])
        return []
    return r.json().get("hits", [])


def download_clip(query, path):
    for q in [query, "business", "office work", "laptop"]:
        hits = pixabay_search(q)
        random.shuffle(hits)
        for hit in hits:
            sizes = hit.get("videos", {})
            for size in ["medium", "large", "small", "tiny"]:
                url = sizes.get(size, {}).get("url")
                if url:
                    try:
                        r = requests.get(url, timeout=60)
                        r.raise_for_status()
                        with open(path, "wb") as f:
                            f.write(r.content)
                        return True
                    except Exception as e:
                        print("Clip download failed:", e)
                        break
    return False


def audio_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path,
    ])
    return float(out.decode().strip())


def make_caption_png(words, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, CAPTION_FONT_SIZE)
    brand_font = ImageFont.truetype(FONT_BOLD, 52)

    words = [w.upper() for w in words]
    key_word = max(words, key=len)
    space = draw.textlength(" ", font=font)
    max_w = W - 140

    lines, current, current_w = [], [], 0
    for w in words:
        ww = draw.textlength(w, font=font)
        add = ww if not current else space + ww
        if current and current_w + add > max_w:
            lines.append(current)
            current, current_w = [w], ww
        else:
            current.append(w)
            current_w += add
    if current:
        lines.append(current)

    line_h = CAPTION_FONT_SIZE + 30
    y = 1150 - (line_h * len(lines)) // 2
    for line in lines:
        total = sum(draw.textlength(w, font=font) for w in line) + space * (len(line) - 1)
        x = (W - total) / 2
        for w in line:
            colour = HIGHLIGHT_COLOR if w == key_word else (255, 255, 255)
            draw.text((x, y), w, font=font, fill=colour, stroke_width=9, stroke_fill=(0, 0, 0))
            x += draw.textlength(w, font=font) + space
        y += line_h

    bw = draw.textlength(BRAND_TEXT, font=brand_font)
    draw.text(((W - bw) / 2, 150), BRAND_TEXT, font=brand_font,
              fill=(255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0))
    img.save(path)


def caption_timings(text, duration):
    words = text.split()
    chunks = [words[i:i + WORDS_PER_CAPTION] for i in range(0, len(words), WORDS_PER_CAPTION)]
    weights = [max(1, sum(len(w) for w in c)) for c in chunks]
    total = sum(weights)
    timings, t = [], 0.0
    for chunk, wt in zip(chunks, weights):
        length = duration * wt / total
        timings.append((chunk, t, t + length))
        t += length
    return timings


async def make_voice(text, path):
    await edge_tts.Communicate(text, VOICE, rate=VOICE_RATE).save(path)


def run(cmd):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print("FFMPEG ERROR:", e.stderr.decode(errors="ignore")[-1500:])
        raise


def build_scene(i, scene):
    text = scene["text"].strip()
    clip = f"{OUT}/clip{i}.mp4"
    mp3 = f"{OUT}/voice{i}.mp3"
    seg = f"{OUT}/seg{i}.mp4"

    if not download_clip(scene.get("search", "business"), clip):
        raise RuntimeError(f"Could not find a stock video for scene {i + 1}")

    asyncio.run(make_voice(text, mp3))
    dur = audio_duration(mp3) + PAD_AFTER_LINE

    timings = caption_timings(text, dur)
    pngs = []
    for k, (chunk, start, end) in enumerate(timings):
        p = f"{OUT}/cap{i}_{k}.png"
        make_caption_png(chunk, p)
        pngs.append((p, start, end))

    filters = [
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "setsar=1,fps=30,eq=brightness=-0.10:saturation=1.1[v0]"
    ]
    for k, (_, start, end) in enumerate(pngs):
        filters.append(
            f"[v{k}][{k + 2}:v]overlay=0:0:enable='between(t,{start:.2f},{end:.2f})'[v{k + 1}]"
        )
    last = f"[v{len(pngs)}]"

    cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", clip, "-i", mp3]
    for p, _, _ in pngs:
        cmd += ["-i", p]
    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", last, "-map", "1:a",
        "-af", "apad",
        "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        seg,
    ]
    run(cmd)
    return os.path.abspath(seg)


def build_video(scenes):
    segments = [build_scene(i, s) for i, s in enumerate(scenes)]

    list_file = f"{OUT}/list.txt"
    with open(list_file, "w") as f:
        for s in segments:
            f.write(f"file '{s}'\n")

    joined = f"{OUT}/joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", joined])

    final = f"{OUT}/reel.mp4"
    if os.path.exists(MUSIC_FILE):
        run([
            "ffmpeg", "-y", "-i", joined, "-stream_loop", "-1", "-i", MUSIC_FILE,
            "-filter_complex",
            f"[1:a]volume={MUSIC_VOLUME}[m];"
            f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final,
        ])
    else:
        print("No music.mp3 found, making the reel without music.")
        os.replace(joined, final)
    return final


def send_to_telegram(video_path, caption):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    with open(video_path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1000], "supports_streaming": True},
            files={"video": f},
            timeout=180,
        )
    if not r.ok:
        raise RuntimeError(f"Telegram error: {r.status_code} {r.text}")


def main():
    data = get_script()
    print("Script:", data["title"])
    video = build_video(data["scenes"])
    caption = f"{data['title']}\n\n{data['caption']}\n\n{data['hashtags']}"
    send_to_telegram(video, caption)
    print("Sent!")


if __name__ == "__main__":
    main()
