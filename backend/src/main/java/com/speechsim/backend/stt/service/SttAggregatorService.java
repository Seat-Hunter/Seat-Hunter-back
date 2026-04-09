package com.speechsim.backend.stt.service;

import com.speechsim.backend.stt.component.AudioBuffer;
import com.speechsim.backend.stt.client.DeepgramClient;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Service;

@Service
public class SttAggregatorService {

    private final AudioBuffer buffer;
    private final DeepgramClient deepgramClient;

    public SttAggregatorService(AudioBuffer buffer,
                                DeepgramClient deepgramClient) {
        this.buffer = buffer;
        this.deepgramClient = deepgramClient;
    }

    @PostConstruct
    public void init() {
        deepgramClient.connect();
    }

    public void processAudioBytes(byte[] audioBytes) {

        System.out.println("STT bytes 처리 시작");

        buffer.add(audioBytes);
        System.out.println("chunk buffer size: " + buffer.size());

        if (buffer.size() >= 5) {
            var chunks = buffer.flush();

            for (byte[] chunk : chunks) {
                deepgramClient.sendAudio(chunk);
            }
        }
    }
}