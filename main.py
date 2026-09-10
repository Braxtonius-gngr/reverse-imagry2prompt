import os
import time
import json
from fastapi import FastAPI, UploadFile, File, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import replicate

app = FastAPI(title="Reverse Imagery to Prompt API")

client = genai.Client()

class ReversePromptSchema(BaseModel):
    medium_type: str = Field(description="Strictly classify as either 'Live-Action' or 'Animated'.")
    core_subject: str = Field(description="The primary subject, their appearance, and exact actions.")
    environment: str = Field(description="The setting, time of day, and background atmosphere.")
    camera_and_motion: str = Field(description="For real-world: lens and camera movement. For animation: perspective and frame pacing.")
    stylistic_modifiers: str = Field(description="For real-world: lighting and film stock. For animation: rendering engine, texture, and artistic style.")
    final_prompt: str = Field(description="A 50-75 word optimized prompt combining all extracted elements, ready to be pasted into a generator.")

class GenerateRequest(BaseModel):
    prompt: str

@app.get("/")
def health_check():
    return {"status": "ok", "message": "API is online"}

@app.post("/api/v1/reverse-prompt")
async def generate_reverse_prompt(file: UploadFile = File(...)):
    temp_file_path = f"temp_{file.filename}"
    
    try:
        # Save incoming file bytes locally
        contents = await file.read()
        with open(temp_file_path, "wb") as buffer:
            buffer.write(contents)

        # Upload to Gemini File API
        uploaded_media = client.files.upload(file=temp_file_path)
        
        # If it's a video, wait for processing
        if file.content_type and file.content_type.startswith('video/'):
            while uploaded_media.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_media = client.files.get(name=uploaded_media.name)
                
            if uploaded_media.state.name == "FAILED":
                raise HTTPException(status_code=500, detail="Video processing failed.")

        system_instruction = """
        You are an elite AI Prompt Reverse-Engineer. Your job is to analyze the provided media and output a highly optimized text prompt designed to recreate it in a generative AI model.
        1. Determine if the media is 'Live-Action' or 'Animated'.
        2. Extract key variables (camera, lighting, rendering style, textures).
        3. Analyze motion and timing.
        4. Synthesize into a dense, optimized prompt block.
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[uploaded_media, "Analyze this media and extract the exact generative prompt parameters."],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=ReversePromptSchema,
                temperature=0.4
            )
        )

        # Cleanup local and remote files
        try:
            client.files.delete(name=uploaded_media.name)
        except Exception:
            pass

        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

        # Parse the JSON response properly
        try:
            response_data = json.loads(response.text)
        except json.JSONDecodeError:
            response_data = response.text

        return {"status": "success", "data": response_data}

    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate")
async def generate_media(request: GenerateRequest):
    try:
        output = replicate.run(
            "black-forest-labs/flux-schnell",
            input={
                "prompt": request.prompt,
                "go_fast": True,
                "megapixels": "1",
                "num_outputs": 1,
                "output_format": "webp"
            }
        )
        return {"status": "success", "media_url": output[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
