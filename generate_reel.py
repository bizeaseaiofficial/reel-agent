import os
import json
import random
import asyncio
import subprocess
import requests
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from google import genai

# ============ SETTINGS (easy things to tweak) ============
GEMINI_MODEL = "gemini-3.8-flash"      # change if Gemini says model not found
VOICE = "en-US-AndrewNeural"           # try en-US-AriaNeural, en-GB-RyanNeural
FONT_SIZE = 84                         # make bigger if text looks small
TEXT_COLOR = (255, 255, 255)
BG_TOP = (20, 30, 80)                  # background gradient colours
BG_BOTTOM = (90, 40, 140)
BRAND_TEXT = "BizEaseAI"
MUSIC_FILE = "music.mp3"               # optional, used only if this file exists
MUSIC_VOLUME = 0.08                    # lower = quieter (0.05 to 0.2)
PAUSE_AFTER_LINE = 0.4                 # seconds of pause after each line
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
You write short Instagram Reel scripts for a brand called {BRAND_TEXT}, which helps
small business owners save time with simple AI tools.

Topic: {topic}

Return ONLY JSON in exactly this shape:
{{
  "title": "short title",
  "scenes": [{{"text": "line 1"}}, {{"text": "line 2"}}],
  "caption": "Instagram caption, 2-3 sentences, friendly, ends with a question",
  "hashtags": "#smallbusiness #ai #productivity"
}}

Rules:
- 6 scenes total.
- Scene 1 is a strong hook that makes people keep watching.
- Last scene is a call to action (follow for more).
- Each scene is under 14 words, plain English, no jargon, no emojis.
"""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return json.loads(resp.text)


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make_slide(text, path):
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    # gradient background
    for y in range(H):
        t = y / H
        colour = tuple(int(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        draw.line([(0, y), (W, y)], fill=colour)

    font = ImageFont.truetype(FONT_BOLD, FONT_SIZE)
    lines = wrap_text(draw, text, font, W - 160)
    line_h = FONT_SIZE + 24
    y = (H - line_h * len(lines)) // 2 - 100
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((W - w) / 2, y), line, font=font, fill=TEXT_COLOR)
        y += line_h

    small = ImageFont.truetype(FONT_BOLD, 48)
    bw = draw.textlength(BRAND_TEXT, font=small)
    draw.text(((W - bw) / 2, 330), BRAND_TEXT, font=small, fill=(255, 200, 80))
    img.save(path)


async def make_voice(text, path):
    await edge_tts.Communicate(text, VOICE).save(path)


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def build_video(scenes):
    segments = []
    for i, scene in enumerate(scenes):
        text = scene["text"].strip()
        png = f"{OUT}/slide{i}.png"
        mp3 = f"{OUT}/voice{i}.mp3"
        seg = f"{OUT}/seg{i}.mp4"
        make_slide(text, png)
        asyncio.run(make_voice(text, mp3))
        run([
            "ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", png, "-i", mp3,
            "-af", f"apad=pad_dur={PAUSE_AFTER_LINE}",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", seg,
        ])
        segments.append(os.path.abspath(seg))

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
            f"[1:a]volume={MUSIC_VOLUME}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", final,
        ])
    else:
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
            timeout=120,
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
