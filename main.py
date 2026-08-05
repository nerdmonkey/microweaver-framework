from app.services.publish import PublishService


def start():
    publish = PublishService()
    publish.run()


if __name__ == "__main__":
    start()
