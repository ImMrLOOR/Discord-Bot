FROM eclipse-temurin:17-jre

WORKDIR /app

# instalar wget
RUN apt-get update && apt-get install -y wget && rm -rf /var/lib/apt/lists/*

# descargar Lavalink automáticamente
RUN wget https://github.com/lavalink-devs/Lavalink/releases/latest/download/Lavalink.jar

# copiar config
COPY application.yml .

CMD ["java", "-jar", "Lavalink.jar"]
