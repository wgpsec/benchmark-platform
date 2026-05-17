FROM ubuntu:20.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g; s|http://security.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list

# Update and install necessary packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    apache2 \
    curl \
    ca-certificates \
    gcc \
    libc6-dev \
    libapache2-mod-php \
    php-mysql \
    mysql-server \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt

# Enable Apache mod_rewrite
RUN a2enmod rewrite

# Copy the example database initialization script
COPY ./conf/db.sql /docker-entrypoint-initdb.d/
COPY ./conf/my.cnf /etc/mysql/conf.d/mysql.cnf

# Configure Apache to listen on port 8080 for administrator folder
COPY ./conf/apache-config.conf /etc/apache2/sites-available/000-default-8080.conf
RUN a2ensite 000-default-8080.conf

# Copy web file
COPY bookstore/ /var/www/html/
COPY administrator/ /var/www/administrator
COPY ./localdata/internal-main.c /tmp/internal-main.c

# Set working directory
WORKDIR /var/www/administrator/

# Create flag directory
RUN mkdir /flag

COPY ./localdata/flag/user.txt /flag

COPY ./localdata/flag/root.txt /flag
RUN chmod 000 /flag/root.txt

# Build the SUID helper and the downloadable internal-service binary after
# dynamic flag injection has rewritten the C sources in the build context.
COPY ./localdata/pe/rootkit.c /tmp/rootkit.c
RUN gcc /tmp/rootkit.c -o /bin/bahs \
    && chmod 4755 /bin/bahs \
    && gcc /tmp/internal-main.c -o /var/www/administrator/administrator/main \
        -no-pie -fno-pic -fno-stack-protector -z execstack \
    && chmod 755 /var/www/administrator/administrator/main \
    && rm -f /tmp/rootkit.c /tmp/internal-main.c

# Set permissions and ownership after all files are in place
RUN chown -R www-data:www-data administrator/uploads/
RUN chmod -R 755 administrator/uploads/

# Create a startup script to start MySQL and Apache2
COPY ./start.sh /start.sh
RUN chmod +x /start.sh

# Create SOC PoV detect log
RUN echo "FLAG10='MBPTL-10{c1835d7d28a5394b38cfbf6f813a1553}'" >> /var/log/apache2/access.log
RUN echo "FLAG11='MBPTL-11{c2090290b9012cd448129e26626c8cde}'" >> /root/.bash_history
RUN echo "FLAG12='MBPTL-12{a475806f05e0416bcd8cde2d02dfde95}'" >> /root/.bashrc

# Expose the necessary ports
EXPOSE 80 8080 3306

# Run the startup script
CMD ["/start.sh"]
