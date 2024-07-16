.PHONY: migrate-apply
migrate-apply: ## apply alembic migrations to database/schema
	alembic upgrade head

.PHONY: migrate-create
migrate-create: ## create new alembic migration
	alembic revision --autogenerate


.PHONY: update
update: ## update front
	git pull
	docker compose restart backend
