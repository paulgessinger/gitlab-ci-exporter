import gitlab
import peewee
from prometheus_client import Gauge

from gitlab_ci_exporter.db import Job, database, prepare_database

gitlab_ci_job_count = Gauge(
    name="gitlab_ci_job_count",
    documentation="The total number of jobs running for various categories",
    labelnames=["status", "job_name"],
)

gitlab_ci_job_latency = Gauge(
    name="gitlab_ci_job_latency",
    documentation="Time of most recent finished job spent in queue",
)


class Updater:
    def __init__(self, host: str, token: str):
        self.gl = gitlab.Gitlab(url=host, private_token=token)

    def _adapt(self, jobs):
        for i, job in enumerate(jobs):
            row = {
                "commit_sha": job.commit["id"],
            }

            for k in  [
                "id",
                "created_at", "started_at", "finished_at", "duration", "queued_duration", "name", "ref", "status", "failure_reason",
            ]:
                if not hasattr(job, k): continue
                row[k] = getattr(job, k)

            yield row




    def tick(self, project: str):
        project = self.gl.projects.get(project)
        jobs = project.jobs.list(
            #  scope=[
                #  "pending",
                #  "created",
                #  "running",
            #  ],
            iterator=True,
            per_page=250,
            order_by="id",
            sort="desc",
        )


        g = (j for _, j in zip(range(1000), self._adapt(jobs)))
        Job.insert_many(g).on_conflict_replace().execute()

        gitlab_ci_job_count.clear()
        for job in Job.select(peewee.fn.COUNT().alias("count"),Job.name,Job.status).group_by(Job.name, Job.status):
            gitlab_ci_job_count.labels(status=job.status, job_name=job.name).inc(job.count)

        latest = Job.select().order_by(Job.finished_at.desc()).get()
        gitlab_ci_job_latency.set(latest.queued_duration)
