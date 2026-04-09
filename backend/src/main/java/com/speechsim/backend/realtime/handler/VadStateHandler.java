package com.speechsim.backend.realtime.handler;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.stereotype.Component;

@Component
public class VadStateHandler {

    public void handle(JsonNode node) {
        System.out.println("vad_state handler 실행");
    }
}