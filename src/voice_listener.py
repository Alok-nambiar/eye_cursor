import os, time, threading, queue

voice_queue = queue.Queue(maxsize=64)

# config
USE_ENGINE = os.environ.get("VOICE_ENGINE", "auto")  # auto / google / vosk

# Try Google SpeechRecognition
try:
    import speech_recognition as sr
    HAVE_SR = True
except:
    HAVE_SR = False

# Try VOSK
try:
    from vosk import Model, KaldiRecognizer
    import pyaudio
    HAVE_VOSK = True
except:
    HAVE_VOSK = False

VOSK_MODEL = r"C:\EYE\EyeCursor\src\models\vosk-model-small-en-us-0.15"

_last = ""
_last_ts = 0
DEDUPE = 0.35

def _should_send(t):
    global _last, _last_ts
    now = time.time()
    if t == _last and (now - _last_ts) < DEDUPE:
        return False
    _last = t
    _last_ts = now
    return True

# -------------------------
# GOOGLE (HIGH LEVEL ENGINE)
# -------------------------
def google_listener():
    if not HAVE_SR:
        print("[VOICE] SpeechRecognition missing.")
        return
    
    r = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except:
        print("[VOICE] Microphone not found.")
        return
    
    with mic as source:
        r.adjust_for_ambient_noise(source, duration=1)

    print("[VOICE] Google WebSpeech listening...")

    while True:
        try:
            with mic as source:
                audio = r.listen(source, timeout=5, phrase_time_limit=6)
            try:
                text = r.recognize_google(audio).lower().strip()
            except:
                continue

            if text and _should_send(text):
                voice_queue.put(text)
                print("[VOICE →]", text)

        except:
            time.sleep(0.1)

# -------------------------
# VOSK (OFFLINE ENGINE)
# -------------------------
def vosk_listener():
    if not HAVE_VOSK:
        print("[VOICE] Vosk missing.")
        return

    if not os.path.exists(VOSK_MODEL):
        print("[VOICE] Vosk model missing:", VOSK_MODEL)
        return

    model = Model(VOSK_MODEL)
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(False)

    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(rate=16000, format=pyaudio.paInt16,
                         channels=1, input=True, frames_per_buffer=16000)
    except Exception as e:
        print("[VOICE] Mic error:", e)
        return
    
    stream.start_stream()
    print("[VOICE] Vosk offline listening...")

    import json

    while True:
        data = stream.read(4000, exception_on_overflow=False)
        if rec.AcceptWaveform(data):
            j = json.loads(rec.Result())
            text = j.get("text", "").lower().strip()
            if text and _should_send(text):
                voice_queue.put(text)
                print("[VOICE →]", text)

# -------------------------
# START LISTENING
# -------------------------
def start_listening():
    engine = USE_ENGINE.lower()

    if engine == "google" and HAVE_SR:
        threading.Thread(target=google_listener, daemon=True).start()
        return

    if engine == "vosk" and HAVE_VOSK:
        threading.Thread(target=vosk_listener, daemon=True).start()
        return

    # AUTO MODE
    if HAVE_SR:
        threading.Thread(target=google_listener, daemon=True).start()
    elif HAVE_VOSK:
        threading.Thread(target=vosk_listener, daemon=True).start()
    else:
        raise RuntimeError("No voice engine available.")
