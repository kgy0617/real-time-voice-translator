import os
import time
import asyncio
import streamlit as st
from google.cloud import speech_v1p1beta1 as speech
from openai import AsyncOpenAI
from dotenv import load_dotenv
import pyaudio
import queue
import threading

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# OpenAI API client
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# Google STT client
google_stt_client = speech.SpeechClient()

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms
FORMAT = pyaudio.paInt16
CHANNELS = 1

# Audio queue for real-time streaming
audio_queue = queue.Queue()
stop_event = threading.Event()  # To signal audio recording thread to stop

# Streaming request generator
def request_stream():
    while True:
        data = audio_queue.get()
        if data is None:
            break
        yield speech.StreamingRecognizeRequest(audio_content=data)

# Google STT configuration
config = speech.RecognitionConfig(
    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
    sample_rate_hertz=RATE,
    language_code="en-US",
    max_alternatives=1,
    enable_automatic_punctuation=True
    # enable_speaker_diarization=True,
    # diarization_speaker_count=2
)

streaming_config = speech.StreamingRecognitionConfig(
    config=config,
    interim_results=True
)

# Audio recording thread function
def record_audio():
    audio_interface = pyaudio.PyAudio()
    stream = audio_interface.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
    try:
        while not stop_event.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_queue.put(data)
    finally:
        stream.stop_stream()
        stream.close()
        audio_interface.terminate()

# OpenAI translation using GPT-4o
async def translate_text(text):
    prompt = f"Translate this English into fluent Korean:\n\n{text}"
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Translation Error]: {str(e)}"

# Streamlit UI setup
st.set_page_config(page_title="Real-time Voice Translator", layout="wide")
st.title("🎙️ Real-time Speech Recognition + Translation (Google STT + GPT-4o)")

col1, col2 = st.columns(2)
with col1:
    st.markdown("### 🗣️ Recognized Speech")
    recognized_box = st.empty()
with col2:
    st.markdown("### 🌐 Translated Korean")
    translated_box = st.empty()

# Start audio recording thread
audio_thread = threading.Thread(target=record_audio, daemon=True)
audio_thread.start()

# Start Google STT streaming
responses = google_stt_client.streaming_recognize(
    config=streaming_config,
    requests=request_stream()
)

# Global state variables
current_transcript = ""
final_transcript = ""
translated_text = ""
sentence_count = 0
translated_count = 0

# Main translation loop
async def run_translation_loop():
    global current_transcript, final_transcript, translated_text
    global sentence_count, translated_count

    for response in responses:
        if not response.results:
            continue

        result = response.results[0]
        if not result.alternatives:
            continue

        transcript = result.alternatives[0].transcript.strip()

        if result.is_final:
            # Append final transcript with spacing
            if sentence_count > 0:
                final_transcript += "\n\n"
            final_transcript += transcript
            sentence_count += 1
            recognized_box.markdown(final_transcript)

            # Translate final sentence
            translated = await translate_text(transcript)

            if translated_count > 0:
                translated_text += "\n\n"
            translated_text += translated
            translated_count += 1

            translated_box.markdown(translated_text)
        else:
            # Display interim result (not accumulated)
            display_text = final_transcript
            if sentence_count > 0 and transcript:
                display_text += "\n\n"
            display_text += transcript
            recognized_box.markdown(display_text)

# Clean up audio thread and queue on exit
def cleanup():
    stop_event.set()              # Signal audio thread to stop
    audio_queue.put(None)         # End request_stream generator
    audio_thread.join(timeout=1)  # Wait for thread to close

# Run the async loop and clean up on shutdown
try:
    asyncio.run(run_translation_loop())
except KeyboardInterrupt:
    pass
finally:
    cleanup()
