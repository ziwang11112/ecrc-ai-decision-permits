"""Direct task submission: no ECRC imports, policy envelopes or client database."""


class DirectClient:
    def __init__(self, limit=None):
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('limit must be a positive integer or None')
        self.limit = limit
        self.first_submissions = 0

    def can_submit(self):
        return self.limit is None or self.first_submissions < self.limit

    def submit_descriptor(self, job):
        if not self.can_submit():
            return None
        self.first_submissions += 1
        return {'idempotency_key': 'direct:' + job['job_hash'],
                'payload': {'job_hash': job['job_hash']}}

    def snapshot(self):
        return {'first_submissions': self.first_submissions, 'limit': self.limit,
                'persistence': 'none'}
