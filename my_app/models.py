from django.db import models
from django.contrib.auth.models import User





class ResumeAnalysis(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    resume = models.FileField(upload_to="resumes/")
    extracted_text = models.TextField()

    skills = models.JSONField(default=list)
    jobs = models.JSONField(default=list)

    match_score = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.user:
            return f"{self.user.username} - {self.match_score}"
        return f"Anonymous - {self.match_score}"