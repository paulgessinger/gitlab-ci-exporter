import gitlab
from prometheus_client import Gauge

gitlab_ci_job_count = Gauge(
    name="gitlab_ci_job_count",
    documentation="The total number of jobs running for various categories",
    labelnames=["status", "job_name"],
)


class Updater:
    def __init__(self, host: str, token: str):
        self.gl = gitlab.Gitlab(url=host, private_token=token)

    def tick(self, project: str):
        project = self.gl.projects.get(project)
        jobs = project.jobs.list(
            scope=[
                "pending",
                "created",
                "running",
            ],
            iterator=True,
        )

        gitlab_ci_job_count.clear()
        for job in jobs:
            gitlab_ci_job_count.labels(status=job.status, job_name=job.name).inc()
