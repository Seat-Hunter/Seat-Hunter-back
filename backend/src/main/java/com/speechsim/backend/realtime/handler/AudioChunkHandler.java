package com.speechsim.backend.realtime.handler;

import com.fasterxml.jackson.databind.JsonNode;
import com.speechsim.backend.stt.service.SttAggregatorService;
import org.springframework.stereotype.Component;

import java.util.Base64;

@Component
public class AudioChunkHandler {

    private final SttAggregatorService sttService;

    public AudioChunkHandler(SttAggregatorService sttService) {
        this.sttService = sttService;
    }

    public void handle(JsonNode node) {

        String base64 = node.has("audio_base64")
                ? node.get("audio_base64").asText()
                : "";

        byte[] audioBytes = Base64.getDecoder().decode(base64);

        System.out.println("audio_chunk handler 실행");

        sttService.processAudioBytes(audioBytes);
    }
}