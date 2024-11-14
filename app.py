import os
import base64
import streamlit as st
from PyPDF2 import PdfReader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains.question_answering import load_qa_chain
from langchain.llms import OpenAI
from langchain.callbacks import get_openai_callback
import PyPDF2
from PIL import Image as Image, ImageOps as ImagOps
import glob
from gtts import gTTS
import time
from streamlit_lottie import st_lottie
import json
import paho.mqtt.client as mqtt

# Función para convertir una imagen a base64
def get_base64_image(file_path):
    with open(file_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode()

# Ruta a la imagen de fondo
image_base64 = get_base64_image("fondo.png")  
# CSS para personalización de fondo y tipografía
st.markdown(
    f"""
    <style>
    .main {{
        background-image: url("data:image/png;base64,{image_base64}");
        background-size: cover;
        background-repeat: no-repeat;
        background-position: center;
    }}
    h1, h2, h3, h4, h5, h6, p, label, .stButton button {{
        font-family: 'Monospace', sans-serif;
        color: #333333;
    }}
    textarea {{
        background-color: #ffffff;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

MQTT_BROKER = "broker.mqttdashboard.com"
MQTT_PORT = 1883
MQTT_TOPIC = "smartoven"

if 'sensor_data' not in st.session_state:
    st.session_state.sensor_data = None

def text_to_speech(text, tld):
    tts = gTTS(text, lang="es", tld=tld, slow=False)
    try:
        my_file_name = text[:20]
    except:
        my_file_name = "audio"
    tts.save(f"temp/{my_file_name}.mp3")
    return my_file_name, text

def remove_files(n):
    mp3_files = glob.glob("temp/*.mp3")
    if len(mp3_files) != 0:
        now = time.time()
        n_days = n * 86400
        for f in mp3_files:
            if os.stat(f).st_mtime < now - n_days:
                os.remove(f)

def send_mqtt_message(message):
    try:
        client = mqtt.Client()
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.publish("h_ctrl", message)
        client.disconnect()
        return True
    except Exception as e:
        st.error(f"Error al enviar mensaje MQTT: {e}")
        return False

def get_mqtt_message():
    message_received = {"received": False, "payload": None}
    
    def on_message(client, userdata, message):
        try:
            payload = json.loads(message.payload.decode())
            message_received["payload"] = payload
            message_received["received"] = True
        except Exception as e:
            st.error(f"Error al procesar mensaje: {e}")
    
    try:
        client = mqtt.Client()
        client.on_message = on_message
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.subscribe(MQTT_TOPIC)
        client.loop_start()
        
        timeout = time.time() + 5
        while not message_received["received"] and time.time() < timeout:
            time.sleep(0.1)
        
        client.loop_stop()
        client.disconnect()
        
        return message_received["payload"]
    
    except Exception as e:
        st.error(f"Error de conexión: {e}")
        return None

try:
    os.mkdir("temp")
except:
    pass

with st.sidebar:
    st.subheader("ASISTENTE DE COCINA")
    st.write("Esta app hace más fácil preparar tus recetas.")

image = Image.open('Remy.png')
col1, col2, col3 = st.columns([1, 2, 3])
with col2:
    st.image(image, caption='Tu receta a un clic', width=500)
st.markdown("<h1 style='text-align: center; color: #5F6E81;'>¿Qué quieres preparar el día de hoy?</h1>", unsafe_allow_html=True)

os.environ['OPENAI_API_KEY'] = st.secrets["settings"]["key"]

pdfFileObj = open('Recetas.pdf', 'rb')
pdf_reader = PyPDF2.PdfReader(pdfFileObj)
text = ""
for page in pdf_reader.pages:
    text += page.extract_text()

text_splitter = CharacterTextSplitter(separator="\n", chunk_size=500, chunk_overlap=20, length_function=len)
chunks = text_splitter.split_text(text)

embeddings = OpenAIEmbeddings()
knowledge_base = FAISS.from_texts(chunks, embeddings)

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Datos del Sensor")
    if st.button("Obtener Lectura"):
        with st.spinner('Obteniendo datos del sensor...'):
            sensor_data = get_mqtt_message()
            st.session_state.sensor_data = sensor_data
            
            if sensor_data:
                st.success("Datos recibidos")
                st.metric("Temperatura", f"{sensor_data.get('Temp', 'N/A')}°C")
            else:
                st.warning("No se recibieron datos del sensor")

with col2:
    st.subheader("Realiza tu consulta")
    user_question = st.text_area("Escribe tu pregunta aquí:")
    
    if user_question:
        if st.session_state.sensor_data:
            enhanced_question = f"Pregunta del usuario:\n{user_question} # ,escribir al final solo los valores de temperatura de la receta y el tiempo en la respuesta"
        else:
            enhanced_question = user_question
        
        docs = knowledge_base.similarity_search(enhanced_question)
        llm = OpenAI(model_name="gpt-4o-mini")
        chain = load_qa_chain(llm, chain_type="stuff")
        
        with st.spinner('Analizando tu pregunta...'):
            with get_openai_callback() as cb:
                response = chain.run(input_documents=docs, question=enhanced_question)
                print(cb)
            
            st.write("Respuesta:", response)

            if st.button("Escuchar"):
                result, output_text = text_to_speech(response, 'es-es')
                audio_file = open(f"temp/{result}.mp3", "rb")
                audio_bytes = audio_file.read()
                st.markdown("## Escucha:")
                st.audio(audio_bytes, format="audio/mp3", start_time=0)

user_question = "" 
TEMPC = st.number_input("Temperatura", key="1")
TIMEC = st.number_input("Tiempo", key="2")
if st.button("Preparar"):
    mensaje = f"{TEMPC} grados, {TIMEC} min"
    send_mqtt_message(mensaje)
    client = mqtt.Client()
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    time.sleep(1)
    client.publish("h_ctrl", mensaje)
    client.disconnect()
    with st.spinner('Enviando mensaje...'):
        if send_mqtt_message(mensaje):
            st.success("Mensaje enviado con éxito")
        else:
            st.error("Error al enviar el mensaje")
