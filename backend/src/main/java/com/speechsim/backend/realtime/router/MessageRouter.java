package com.speechsim.backend.realtime.router;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;
import com.speechsim.backend.realtime.handler.AudioChunkHandler;
import com.speechsim.backend.realtime.handler.VadStateHandler;
import com.speechsim.backend.realtime.handler.PartialTranscriptHandler;

@Component
public class MessageRouter {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private final AudioChunkHandler audioHandler;
    private final VadStateHandler vadHandler;
    private final PartialTranscriptHandler partialHandler;

    public MessageRouter(AudioChunkHandler audioHandler,
                         VadStateHandler vadHandler,
                         PartialTranscriptHandler partialHandler) {
        this.audioHandler = audioHandler;
        this.vadHandler = vadHandler;
        this.partialHandler = partialHandler;
    }

    public void route(String message) {
        try {
            JsonNode node = objectMapper.readTree(message);
            String type = node.get("type").asText();

            switch (type) {

                case "audio_chunk":
                    audioHandler.handle(node);
                    break;

                case "vad_state":
                    vadHandler.handle(node);
                    break;

                case "partial_transcript":
                    partialHandler.handle(node);
                    break;

                default:
                    System.out.println("unknown type: " + type);
            }

        } catch (Exception e) {
            System.out.println("message parse error");
            e.printStackTrace();
        }
    }
}