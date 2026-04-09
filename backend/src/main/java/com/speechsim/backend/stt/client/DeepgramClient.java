package com.speechsim.backend.stt.client;

import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;

@Component
public class DeepgramClient {

    @Value("${deepgram.api.key}")
    private String apiKey;

    private WebSocketClient client;

    private boolean isConnected = false;

    public void connect() {
        try {
            URI uri = new URI(
                "wss://api.deepgram.com/v1/listen?encoding=webm&sample_rate=48000"
            );

            client = new WebSocketClient(uri) {

                @Override
                public void onOpen(ServerHandshake handshake) {
                    System.out.println("Deepgram 연결됨");
                    isConnected = true;
                }

                @Override
                public void onMessage(String message) {
                    System.out.println("Deepgram 응답: " + message);

                    if (message.contains("transcript")) {
                        System.out.println(">>> STT 결과 감지됨");
                    }
                }

                @Override
                public void onClose(int code, String reason, boolean remote) {
                    System.out.println("Deepgram 연결 종료");
                    isConnected = false;
                }

                @Override
                public void onError(Exception ex) {
                    ex.printStackTrace();
                }
            };

            client.addHeader("Authorization", "Token " + apiKey);
            client.connect();

        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public void sendAudio(byte[] audioBytes) {

        if (client == null || !client.isOpen()) {
            System.out.println("Deepgram 재연결 시도");
            connect();

            try {
                Thread.sleep(500); // 연결 대기
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }

        System.out.println(">>> Deepgram으로 audio 전송됨");
        client.send(audioBytes);
    }
}