docker compose -f docker/compose_all.yaml down
docker compose -f docker/compose_all.yaml up -d

# Wait some seconds for containers startup
sleep 2

docker compose -f docker/compose_all.yaml logs --follow
