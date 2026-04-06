from django.db import models


class Template(models.Model):
    class Type(models.TextChoices):
        WEEKDAY = "weekday", "Weekday"
        WEEKEND = "weekend", "Weekend"

    name = models.CharField(max_length=100)
    type = models.CharField(max_length=10, choices=Type.choices)
    blocks = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.type})"


class Rule(models.Model):
    text = models.TextField()
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-priority"]

    def __str__(self):
        return self.text[:80]
