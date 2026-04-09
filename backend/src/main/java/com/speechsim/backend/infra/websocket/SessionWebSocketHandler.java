package com.speechsim.backend.infra.websocket;

import com.speechsim.backend.realtime.service.ConnectionManager;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import com.speechsim.backend.realtime.router.MessageRouter;

@Component
public class SessionWebSocketHandler extends TextWebSocketHandler {

    private final ConnectionManager connectionManager;
    private final MessageRouter messageRouter;

    public SessionWebSocketHandler(ConnectionManager connectionManager,
                               MessageRouter messageRouter) {
                                this.connectionManager = connectionManager;
                                this.messageRouter = messageRouter;
                            }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {

        String uri = session.getUri().toString();
        String sessionId = uri.substring(uri.lastIndexOf("/") + 1);

        connectionManager.connect(sessionId, session);

        System.out.println("연결됨: " + sessionId);
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        messageRouter.route(message.getPayload());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {

        String uri = session.getUri().toString();
        String sessionId = uri.substring(uri.lastIndexOf("/") + 1);

        connectionManager.disconnect(sessionId);

        System.out.println("연결 종료: " + sessionId);
    }
}