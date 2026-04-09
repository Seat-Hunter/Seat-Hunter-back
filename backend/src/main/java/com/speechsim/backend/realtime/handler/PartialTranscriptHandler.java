package com.speechsim.backend.realtime.handler;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.stereotype.Component;

@Component
public class PartialTranscriptHandler {

    public void handle(JsonNode node) {
        System.out.println("partial_transcript handler 실행");
    }
}