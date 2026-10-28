data "aws_availability_zones" "available" { state = "available" }
resource "aws_vpc" "worker" {
  cidr_block = "10.88.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support = true
  tags = { Name = "${var.project}-worker-vpc" }
}
resource "aws_internet_gateway" "worker" {
  vpc_id = aws_vpc.worker.id
  tags = { Name = "${var.project}-igw" }
}
resource "aws_subnet" "public" {
  count = 2
  vpc_id = aws_vpc.worker.id
  cidr_block = cidrsubnet(aws_vpc.worker.cidr_block, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
  tags = { Name = "${var.project}-worker-public-${count.index + 1}" }
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.worker.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.worker.id
  }
}
resource "aws_route_table_association" "public" {
  count = 2
  subnet_id = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
resource "aws_security_group" "worker" {
  name_prefix = "${var.project}-worker-"
  description = "Zero inbound ports; worker initiates outbound HTTPS/Postgres only"
  vpc_id = aws_vpc.worker.id
  egress {
    from_port = 443
    to_port = 443
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${var.project}-worker" }
}
# No NAT gateways, no load balancers, no ECS public listener.
