# Use an official Node.js runtime as the base image
FROM node:17

# Set the working directory in the container
WORKDIR /app
# Copy your Node.js script into the container
COPY arraySum_chained.js /app/arraySum_chained.js

# Specify the command to run when the container starts
ENTRYPOINT ["node", "arraySum_chained.js"]
